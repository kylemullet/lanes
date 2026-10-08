"""push_guard.py: one rule for every push that needs no operator OK (LANES-5)."""
import sys

import pytest

import backlog_new as bn
import lanes_config as lc
import push_guard as pg
from conftest import git

MINE = f"Tester's session on Tester+{sys.platform}@host"
THEIRS = "Kyle's session on kyle-win@KylesAsusZephyr"


def _issue(issue_id, status="open", marker=None):
    project = issue_id.rsplit("-", 1)[0]
    current = marker or "Open."
    return (f"---\nid: {issue_id}\nproject: {project}\ntype: story\nstatus: {status}\npriority: normal\n"
            f"blocked_on: null\nassignee: tester\nreported_by: claude\nopened: 2026-10-01\nclosed: null\n"
            f"commit: null\nresolution: null\nlinks: []\n---\n\n# {issue_id} — thing\n\n## Context\n\nx\n\n"
            f"## Current status\n\n{current}\n\n## Resolution\n\n(fill on close)\n")


def _marker(who, kind="RESERVED, NOT STARTED"):
    return f"⏳ IN-PROGRESS (2026-10-07 08:00, {who}) — **{kind}.** Queued."


def _write(clone, rel, text):
    p = clone / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return rel


def _commit(clone, rel, text, msg="docs(backlog): edit"):
    _write(clone, rel, text)
    git("add", rel, cwd=clone)
    git("commit", "-q", "-m", msg, cwd=clone)


def _clone(origin, path, tmp_path):
    git("clone", "-q", str(origin), str(path), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=path)
    git("config", "user.name", "Tester", cwd=path)
    return path


CORE1 = "docs/backlog/CORE/CORE-1-thing.md"
CORE2 = "docs/backlog/CORE/CORE-2-thing.md"
CORE3 = "docs/backlog/CORE/CORE-3-thing.md"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A bare origin with CORE-1 open, CORE-2 claimed by THIS machine, CORE-3 claimed by
    another machine; and the main clone, solo mode (no config)."""
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    seed = _clone(origin, tmp_path / "seed", tmp_path)
    _write(seed, ".gitignore", "docs/backlog/INDEX.md\ndocs/backlog/index.html\n")
    _write(seed, CORE1, _issue("CORE-1"))
    _write(seed, CORE2, _issue("CORE-2", "in-progress", _marker(MINE)))
    _write(seed, CORE3, _issue("CORE-3", "in-progress", _marker(THEIRS)))
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "init", cwd=seed)
    git("push", "-q", "origin", "main", cwd=seed)
    clone = _clone(origin, tmp_path / "proj", tmp_path)
    monkeypatch.chdir(clone)
    return origin, clone, seed


def _cfg(clone):
    return lc.resolve({}, user_name="Tester")


def test_ok_free_defaults_to_the_backlog_dir_not_main_direct_paths():
    assert lc.resolve({}, user_name="T")["ok_free_paths"] == ["docs/backlog/"]
    assert lc.resolve({"backlog": {"dir": "work/queue/"}}, user_name="T")["ok_free_paths"] == ["work/queue/"]
    raw = {"git": {"ok_free_paths": ["docs/backlog/", "docs/session-assets/"]}}
    assert lc.resolve(raw, user_name="T")["ok_free_paths"] == ["docs/backlog/", "docs/session-assets/"]
    assert any("list" in p.message for p in lc.validate({"git": {"ok_free_paths": "docs/"}}))


def test_backlog_only_commit_pushes_without_an_ok(setup):
    origin, clone, _ = setup
    _commit(clone, CORE1, _issue("CORE-1").replace("Open.", "Still open, re-read 10-07."))
    assert pg.main(["--ok-free", "--push"]) == 0
    assert git("rev-parse", "main", cwd=origin) == git("rev-parse", "HEAD", cwd=clone)


def test_anything_outside_ok_free_paths_is_refused_and_nothing_moves(setup, capsys):
    origin, clone, _ = setup
    before = git("rev-parse", "main", cwd=origin)
    _commit(clone, CORE1, _issue("CORE-1").replace("Open.", "x"))
    _commit(clone, "src/app.py", "x = 1\n", msg="feat: code")
    assert pg.main(["--ok-free", "--push"]) == pg.REFUSED
    assert "src/app.py" in capsys.readouterr().err
    assert git("rev-parse", "main", cwd=origin) == before


def test_standing_docs_are_main_direct_but_not_ok_free(setup):
    _, clone, _ = setup
    _commit(clone, "docs/PROJECT_STATE.md", "# state\n", msg="docs: state")
    cfg = _cfg(clone)
    assert pg.problems(clone, cfg, pg.CLAIM) == []
    assert any("ok_free_paths" in p for p in pg.problems(clone, cfg, pg.OK_FREE))


def test_editing_another_machines_claim_is_refused(setup, capsys):
    origin, clone, _ = setup
    before = git("rev-parse", "main", cwd=origin)
    _commit(clone, CORE3, _issue("CORE-3"), msg="docs(backlog): release CORE-3")
    assert pg.main(["--ok-free", "--push"]) == pg.REFUSED
    err = capsys.readouterr().err
    assert "another machine's claim" in err and "kyle-win" in err
    assert git("rev-parse", "main", cwd=origin) == before


def test_releasing_this_machines_own_claim_passes(setup):
    origin, clone, _ = setup
    _commit(clone, CORE2, _issue("CORE-2"), msg="docs(backlog): release CORE-2")
    assert pg.main(["--ok-free", "--push"]) == 0
    assert git("rev-parse", "main", cwd=origin) == git("rev-parse", "HEAD", cwd=clone)


@pytest.mark.parametrize("line, author", [
    (_marker(THEIRS), ("kyle", "kyle-win")),
    ("⏳ IN-PROGRESS (2026-10-07 04:00, Kyle's session on kyle-mac@Air, worktree w, branch b) — **ACTIVE LANE.**",
     ("kyle", "kyle-mac")),
    ("⏳ IN-PROGRESS (2026-09-16, Kyle's session) — **ACTIVE LANE.**", ("kyle", None)),
    ("Open.", None),
])
def test_marker_author(line, author):
    assert pg.marker_author(line) == author


def test_a_red_backlog_check_is_refused(setup, capsys):
    _, clone, _ = setup
    _commit(clone, "docs/backlog/CORE/CORE-4-thing.md", "no frontmatter\n")
    assert pg.main(["--ok-free"]) == pg.REFUSED
    assert "--check is red" in capsys.readouterr().err


def test_a_rejected_push_rebases_and_converges(setup, tmp_path):
    origin, clone, seed = setup
    git("pull", "-q", cwd=seed)
    _commit(seed, CORE1, _issue("CORE-1").replace("Open.", "seed's edit"))
    git("push", "-q", "origin", "main", cwd=seed)
    _commit(clone, CORE2, _issue("CORE-2", "in-progress", _marker(MINE)).replace("Queued.", "Queued, still."))
    code, msg = pg.push(clone, _cfg(clone), pg.OK_FREE)
    assert code == 0, msg
    log = git("log", "--format=%s", "main", cwd=origin).splitlines()
    assert len(log) == 3


def test_add_commits_only_the_named_paths(setup):
    origin, clone, _ = setup
    _write(clone, CORE1, _issue("CORE-1").replace("Open.", "fixed staleness"))
    _write(clone, CORE2, _issue("CORE-2", "in-progress", _marker(MINE)).replace("Queued.", "unrelated"))
    assert pg.main(["--ok-free", "--push", "--add", CORE1, "-m", "docs(backlog): CORE-1 staleness"]) == 0
    assert git("show", "--name-only", "--format=", "main", cwd=origin) == CORE1
    assert CORE2 in git("status", "--porcelain", cwd=clone)


def test_refused_from_a_lane_worktree(setup, capsys):
    _, clone, _ = setup
    wt = clone.parent / "proj-lane"
    git("worktree", "add", "-q", "-b", "lane", str(wt), cwd=clone)
    assert pg.main(["--ok-free", "--root", str(wt)]) == pg.REFUSED
    assert "lane worktree" in capsys.readouterr().err


def test_backlog_new_push_mints_commits_and_publishes(setup, monkeypatch):
    origin, clone, _ = setup
    import backlog_index as bidx
    monkeypatch.setattr(bidx, "regenerate", lambda: None)
    assert bn.main(["--root", str(clone), "CORE", "a raised issue", "--reported-by=claude", "--push"]) == 0
    assert git("log", "-1", "--format=%s", "main", cwd=origin) == "docs(backlog): open CORE-4 — a raised issue"
    assert git("show", "--name-only", "--format=", "main", cwd=origin) == "docs/backlog/CORE/CORE-4-a-raised-issue.md"


def test_backlog_new_push_is_refused_in_a_worktree_before_minting(setup, monkeypatch):
    _, clone, _ = setup
    wt = clone.parent / "proj-lane"
    git("worktree", "add", "-q", "-b", "lane", str(wt), cwd=clone)
    with pytest.raises(SystemExit) as e:
        bn.main(["--root", str(wt), "CORE", "a raised issue", "--reported-by=claude", "--push"])
    assert e.value.code == 2
    assert not list((wt / "docs/backlog/CORE").glob("CORE-4-*"))
