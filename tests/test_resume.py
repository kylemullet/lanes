"""Claims carry the machine (LANES-7): resume onto a second machine, machine-scoped evidence."""
import datetime
import sys

import pytest

import lanes_claim as lcl
import lanes_doctor as ld
import push_guard as pg
from conftest import git

NOW = datetime.datetime(2026, 10, 8, 9, 0)
CONFIG = f"""[backlog]
projects = ["CORE"]

[[operators]]
name = "KyleMac"
platform = "{sys.platform}"
id = "kyle-mac"
short = "kyle"
certifies = true

[[operators]]
name = "KyleWin"
platform = "{sys.platform}"
id = "kyle-win"
short = "kyle"
certifies = true

[[operators]]
name = "Mike"
platform = "{sys.platform}"
id = "mike-win"
short = "mike"
"""
REL = "docs/backlog/CORE/CORE-1-thing.md"
ACTIVE = ("⏳ IN-PROGRESS (2026-10-08 07:00, {who}'s session on {mid}@{host}, worktree proj-core-1, "
          "branch core-1-work) — **ACTIVE LANE.** Expected files: src/x.py.")


def _issue(marker):
    return ("---\nid: CORE-1\nproject: CORE\ntype: story\nstatus: in-progress\nlane: CORE-1@2026-10-08\n"
            "priority: normal\nblocked_on: null\nassignee: kyle\nreported_by: kyle\nopened: 2026-10-01\n"
            "closed: null\ncommit: null\nresolution: null\nlinks: []\n---\n\n# CORE-1 — thing\n\n"
            f"## Context\n\nx\n\n## Current status\n\n{marker}\n\n## Resolution\n\n(fill on close)\n")


def _clone(origin, path, tmp_path, name):
    git("clone", "-q", str(origin), str(path), cwd=tmp_path)
    git("config", "user.email", f"{name}@example.com", cwd=path)
    git("config", "user.name", name, cwd=path)
    return path


@pytest.fixture
def two_machines(tmp_path, monkeypatch):
    """origin: CORE-1 ACTIVE on kyle-mac with its branch pushed; a kyle-win and a mike clone."""
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    mac = _clone(origin, tmp_path / "mac" / "proj", tmp_path, "KyleMac")
    (mac / ".claude/lanes").mkdir(parents=True)
    (mac / ".claude/lanes/config.toml").write_text(CONFIG, encoding="utf-8")
    (mac / ".gitignore").write_text("docs/backlog/INDEX.md\ndocs/backlog/index.html\n", encoding="utf-8")
    (mac / "docs/backlog/CORE").mkdir(parents=True)
    (mac / REL).write_text(_issue(ACTIVE.format(who="Kyle", mid="kyle-mac", host="mac-host")), encoding="utf-8")
    git("add", "-A", cwd=mac)
    git("commit", "-q", "-m", "init", cwd=mac)
    git("push", "-q", "origin", "main", cwd=mac)
    git("checkout", "-q", "-b", "core-1-work", cwd=mac)
    (mac / "src").mkdir()
    (mac / "src/x.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "src/x.py", cwd=mac)
    git("commit", "-q", "-m", "wip: the mac half", cwd=mac)
    git("push", "-q", "origin", "core-1-work", cwd=mac)
    git("checkout", "-q", "main", cwd=mac)
    win = _clone(origin, tmp_path / "win" / "proj", tmp_path, "KyleWin")
    mike = _clone(origin, tmp_path / "mike" / "proj", tmp_path, "Mike")
    monkeypatch.setattr(lcl, "_now", lambda: NOW)
    return origin, mac, win, mike


def test_resume_rehomes_the_lane_and_publishes_the_marker(two_machines, monkeypatch, capsys):
    origin, _, win, _ = two_machines
    monkeypatch.chdir(win)
    assert lcl.main(["--resume", "CORE-1"]) == 0, capsys.readouterr().err
    wt = win.parent / "proj-core-1"
    assert (wt / "src/x.py").read_text(encoding="utf-8") == "x = 1\n"        # the mac half came across
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt) == "core-1-work"
    text = git("show", f"main:{REL}", cwd=origin)
    line = next(l for l in text.splitlines() if l.startswith("⏳"))
    assert "Kyle's session on kyle-win@" in line and "(2026-10-08 09:00," in line
    assert "worktree proj-core-1, branch core-1-work) — **ACTIVE LANE.** Expected files: src/x.py." in line
    assert line.endswith("Resumed from kyle-mac@mac-host (claimed 2026-10-08 07:00).")
    assert git("log", "-1", "--format=%s", "main", cwd=origin) == \
        "docs(backlog): CORE-1 resumed on kyle-win (worktree proj-core-1, branch core-1-work)"


def test_another_persons_lane_is_refused(two_machines, monkeypatch, capsys):
    origin, _, _, mike = two_machines
    before = git("rev-parse", "main", cwd=origin)
    monkeypatch.chdir(mike)
    assert lcl.main(["--resume", "CORE-1"]) == lcl.NOT_CLAIMED
    assert "another person's claim" in capsys.readouterr().err
    assert git("rev-parse", "main", cwd=origin) == before
    assert not (mike.parent / "proj-core-1").exists()


def test_a_lane_this_machine_owns_is_refused(two_machines, monkeypatch, capsys):
    _, mac, _, _ = two_machines
    monkeypatch.chdir(mac)
    assert lcl.main(["--resume", "CORE-1"]) == lcl.NOT_CLAIMED
    assert "already owns" in capsys.readouterr().err


def test_an_unpushed_branch_is_refused(two_machines, monkeypatch, capsys):
    origin, _, win, _ = two_machines
    git("push", "-q", "origin", "--delete", "core-1-work", cwd=win)
    monkeypatch.chdir(win)
    assert lcl.main(["--resume", "CORE-1"]) == lcl.NOT_CLAIMED
    assert "the branch is the hand-off" in capsys.readouterr().err


def _cfg(clone):
    return pg.load_cfg(clone)


def test_guard_allows_the_resume_rewrite_but_not_a_different_branch(two_machines):
    _, _, win, _ = two_machines
    mine = ACTIVE.format(who="Kyle", mid="kyle-win", host="zephyr")
    (win / REL).write_text(_issue(mine), encoding="utf-8")
    git("commit", "-qam", "resume by hand", cwd=win)
    assert pg.foreign_claim_edits(win, _cfg(win)) == []
    (win / REL).write_text(_issue(mine.replace("core-1-work", "other-work")), encoding="utf-8")
    git("commit", "-qam", "a different lane", cwd=win)
    assert pg.foreign_claim_edits(win, _cfg(win))


def test_guard_refuses_another_persons_marker_even_rewritten_to_this_machine(two_machines):
    _, _, _, mike = two_machines
    (mike / REL).write_text(_issue(ACTIVE.format(who="Mike", mid="mike-win", host="h")), encoding="utf-8")
    git("commit", "-qam", "take it", cwd=mike)
    assert pg.foreign_claim_edits(mike, _cfg(mike))


# --- the doctor: evidence is machine-scoped ----------------------------------------------

def _classify(clone, marker, machine_id, worktrees=frozenset()):
    return ld.classify_claim("CORE-1", _issue(marker), NOW, clone, set(worktrees), machine_id)


def test_another_machines_lane_with_its_branch_pushed_is_live(two_machines):
    _, _, win, _ = two_machines
    git("fetch", "-q", "origin", cwd=win)
    c = _classify(win, ACTIVE.format(who="Kyle", mid="kyle-mac", host="mac-host"), "kyle-win")
    assert c.status == ld.OK and "on kyle-mac@mac-host" in c.detail and "branch core-1-work" in c.detail


def test_another_machines_lane_without_a_branch_says_its_worktree_is_invisible(two_machines):
    _, _, win, _ = two_machines
    marker = ACTIVE.format(who="Kyle", mid="kyle-mac", host="mac-host").replace("core-1-work", "gone-work")
    c = _classify(win, marker, "kyle-win", worktrees={"proj-core-1"})
    assert c.status == ld.WARN and "invisible from here" in c.detail
    assert "worktree proj-core-1 present" not in c.detail          # a same-named local worktree is not evidence


def test_this_machines_lane_still_counts_its_local_worktree(two_machines):
    _, mac, _, _ = two_machines
    marker = ACTIVE.format(who="Kyle", mid="kyle-mac", host="mac-host").replace("core-1-work", "gone-work")
    c = _classify(mac, marker, "kyle-mac", worktrees={"proj-core-1"})
    assert c.status == ld.OK and "worktree proj-core-1 present" in c.detail
