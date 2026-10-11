"""lanes_pull.py: sync the main branch on a clone a file-sync mirror has already updated (LANES-38).

The incident: a directory that is both git-tracked and mirrored by a sync client received
a landing's bytes before the clone pulled. `git pull --rebase` refused on "unstaged
changes" that were byte-identical to origin, and the clone sat 63 commits behind. The
fix reconciles identical paths without writing them (a write would ripple back through
the mirror), refuses only on paths that genuinely differ, and names them.
"""
import os
import shutil

import pytest

import lanes_pull as lp
from conftest import git, write_issue


def _clone(origin, path):
    git("clone", "-q", str(origin), str(path), cwd=path.parent)
    git("config", "user.email", "t@example.com", cwd=path)
    git("config", "user.name", "Tester", cwd=path)
    return path


@pytest.fixture
def pair(tmp_path, monkeypatch):
    """A bare origin, a clone that lands, and the mirror clone the test runs the pull in."""
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    lander = _clone(origin, tmp_path / "lander")
    (lander / "README.md").write_text("# proj\n", encoding="utf-8")
    (lander / "fixtures").mkdir()
    (lander / "fixtures" / "a.txt").write_text("a\n", encoding="utf-8")
    git("add", "README.md", "fixtures/a.txt", cwd=lander)
    git("commit", "-q", "-m", "init", cwd=lander)
    git("push", "-q", "origin", "main", cwd=lander)
    mirror = _clone(origin, tmp_path / "mirror")
    monkeypatch.chdir(mirror)
    return origin, lander, mirror


def land(lander, files, subject="feat: a landing"):
    """Write (or delete, value None) the files in the landing clone, commit by path, push."""
    for rel, content in files.items():
        p = lander / rel
        if content is None:
            git("rm", "-q", rel, cwd=lander)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        git("add", rel, cwd=lander)
    git("commit", "-q", "-m", subject, cwd=lander)
    git("push", "-q", "origin", "main", cwd=lander)
    return git("rev-parse", "HEAD", cwd=lander)


def deliver(lander, mirror, rels):
    """The sync client copies the landed bytes into the mirror clone before git sees them."""
    for rel in rels:
        src, dst = lander / rel, mirror / rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        elif dst.exists():
            dst.unlink()


def status(repo):
    """Dirty paths; read raw, since the first porcelain row starts with a significant space."""
    import subprocess
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo,
                         check=True, capture_output=True, text=True, encoding="utf-8").stdout
    return sorted(line[3:] for line in out.splitlines() if line)


def head(repo):
    return git("rev-parse", "HEAD", cwd=repo)


def test_a_clean_clone_behind_origin_fast_forwards(pair, capsys):
    origin, lander, mirror = pair
    old = head(mirror)
    tip = land(lander, {"fixtures/b.txt": "b\n"})
    assert lp.main([]) == 0
    assert head(mirror) == tip and (mirror / "fixtures" / "b.txt").read_text() == "b\n"
    assert git("rev-parse", "ORIG_HEAD", cwd=mirror) == old
    assert status(mirror) == []
    assert "fast-forward" in capsys.readouterr().out


def test_mirror_delivered_paths_reconcile_without_a_write(pair, capsys):
    """The incident's shape: a modified tracked file and a new untracked one, both identical
    to origin, plus one landed path the mirror has NOT delivered yet."""
    origin, lander, mirror = pair
    tip = land(lander, {"README.md": "# proj\n\nmore\n", "fixtures/b.txt": "b\n", "fixtures/c.txt": "c\n"})
    deliver(lander, mirror, ["README.md", "fixtures/b.txt"])
    assert status(mirror) == ["README.md", "fixtures/b.txt"]
    before = {rel: os.stat(mirror / rel).st_mtime_ns for rel in ("README.md", "fixtures/b.txt")}
    assert lp.main([]) == 0
    assert head(mirror) == tip and status(mirror) == []
    assert {rel: os.stat(mirror / rel).st_mtime_ns for rel in before} == before     # never written
    assert (mirror / "fixtures" / "c.txt").read_text() == "c\n"                     # the undelivered one was checked out
    out = capsys.readouterr().out
    assert "2 path(s) already identical to origin/main are reconciled without a write" in out
    assert "1 path(s) checked out" in out and "2 reconciled" in out


def test_a_genuine_local_change_refuses_and_moves_nothing(pair, capsys):
    origin, lander, mirror = pair
    old = head(mirror)
    land(lander, {"README.md": "# proj\n\nmore\n", "fixtures/b.txt": "b\n"})
    (mirror / "README.md").write_text("# proj\n\nmine\n", encoding="utf-8")
    deliver(lander, mirror, ["fixtures/b.txt"])
    assert lp.main([]) == lp.NOT_SYNCED
    assert head(mirror) == old
    assert (mirror / "README.md").read_text() == "# proj\n\nmine\n"
    err = capsys.readouterr().err
    assert "REFUSED" in err and "README.md  (differs from origin/main)" in err
    assert "fixtures/b.txt" not in err                       # only the paths that genuinely differ are named


def test_a_new_local_file_origin_lacks_is_carried(pair, capsys):
    origin, lander, mirror = pair
    (mirror / "notes.md").write_text("draft\n", encoding="utf-8")
    tip = land(lander, {"fixtures/b.txt": "b\n"})
    assert lp.main([]) == 0
    assert head(mirror) == tip and status(mirror) == ["notes.md"]
    assert (mirror / "notes.md").read_text() == "draft\n"
    assert "1 new local file(s) stay untracked" in capsys.readouterr().out


def test_local_commits_rebase_over_a_mirror_delivered_tree(pair, capsys):
    origin, lander, mirror = pair
    (mirror / "local.txt").write_text("local\n", encoding="utf-8")
    git("add", "local.txt", cwd=mirror)
    git("commit", "-q", "-m", "docs: a local commit", cwd=mirror)
    tip = land(lander, {"fixtures/b.txt": "b\n"})
    deliver(lander, mirror, ["fixtures/b.txt"])
    before = os.stat(mirror / "fixtures" / "b.txt").st_mtime_ns
    assert lp.main([]) == 0
    assert git("rev-list", "--count", f"{tip}..HEAD", cwd=mirror) == "1"
    assert git("log", "-1", "--format=%s", cwd=mirror) == "docs: a local commit"
    assert status(mirror) == [] and os.stat(mirror / "fixtures" / "b.txt").st_mtime_ns == before
    assert len(git("worktree", "list", cwd=mirror).splitlines()) == 1          # the scratch worktree is gone
    assert "rebase 1 local commit(s)" in capsys.readouterr().out


def test_ff_only_refuses_local_commits(pair, capsys):
    origin, lander, mirror = pair
    (mirror / "local.txt").write_text("local\n", encoding="utf-8")
    git("add", "local.txt", cwd=mirror)
    git("commit", "-q", "-m", "docs: a local commit", cwd=mirror)
    old = head(mirror)
    land(lander, {"fixtures/b.txt": "b\n"})
    assert lp.main(["--ff-only"]) == lp.NOT_SYNCED
    assert head(mirror) == old
    assert "--ff-only" in capsys.readouterr().err


def test_a_rebase_conflict_aborts_refuses_and_leaves_no_scratch(pair, capsys):
    origin, lander, mirror = pair
    (mirror / "README.md").write_text("# proj\n\nmine\n", encoding="utf-8")
    git("commit", "-q", "-am", "docs: mine", cwd=mirror)
    old = head(mirror)
    land(lander, {"README.md": "# proj\n\ntheirs\n"})
    assert lp.main([]) == lp.NOT_SYNCED
    assert head(mirror) == old and status(mirror) == []
    assert len(git("worktree", "list", cwd=mirror).splitlines()) == 1
    assert not list(mirror.parent.glob("lanes-pull-*"))
    assert "conflicts" in capsys.readouterr().err


def test_a_path_deleted_on_origin_and_already_gone_here_reconciles(pair):
    origin, lander, mirror = pair
    tip = land(lander, {"fixtures/a.txt": None})
    deliver(lander, mirror, ["fixtures/a.txt"])
    assert status(mirror) == ["fixtures/a.txt"]
    assert lp.main([]) == 0
    assert head(mirror) == tip and status(mirror) == [] and not (mirror / "fixtures" / "a.txt").exists()


def test_a_path_deleted_on_origin_the_mirror_still_has_is_removed(pair):
    origin, lander, mirror = pair
    tip = land(lander, {"fixtures/a.txt": None})
    assert lp.main([]) == 0
    assert head(mirror) == tip and status(mirror) == [] and not (mirror / "fixtures").exists()


def test_a_staged_identical_change_reconciles(pair):
    origin, lander, mirror = pair
    tip = land(lander, {"fixtures/b.txt": "b\n"})
    deliver(lander, mirror, ["fixtures/b.txt"])
    git("add", "fixtures/b.txt", cwd=mirror)
    assert lp.main([]) == 0
    assert head(mirror) == tip and status(mirror) == []


def test_dry_run_classifies_and_moves_nothing(pair, capsys):
    origin, lander, mirror = pair
    old = head(mirror)
    land(lander, {"README.md": "# proj\n\nmore\n", "fixtures/b.txt": "b\n"})
    deliver(lander, mirror, ["README.md"])
    (mirror / "notes.md").write_text("draft\n", encoding="utf-8")
    assert lp.main(["--dry-run"]) == 0
    assert head(mirror) == old and status(mirror) == ["README.md", "notes.md"]
    out = capsys.readouterr().out
    assert "would fast-forward" in out and "reconcile  README.md" in out and "carry      notes.md" in out


def test_up_to_date_leaves_a_dirty_tree_alone(pair, capsys):
    origin, lander, mirror = pair
    (mirror / "README.md").write_text("# proj\n\nmine\n", encoding="utf-8")
    assert lp.main([]) == 0
    assert (mirror / "README.md").read_text() == "# proj\n\nmine\n"
    out = capsys.readouterr().out
    assert "up to date" in out and "1 local change(s) left as they are" in out


def test_refuses_off_the_main_branch(pair, capsys):
    origin, lander, mirror = pair
    git("checkout", "-q", "-b", "topic", cwd=mirror)
    assert lp.main([]) == lp.NOT_SYNCED
    assert "not `main`" in capsys.readouterr().err


def test_refuses_inside_a_rebase(pair, capsys):
    import subprocess
    origin, lander, mirror = pair
    (mirror / "README.md").write_text("# proj\n\nmine\n", encoding="utf-8")
    git("commit", "-q", "-am", "docs: mine", cwd=mirror)
    land(lander, {"README.md": "# proj\n\ntheirs\n"})
    git("fetch", "-q", "origin", cwd=mirror)
    subprocess.run(["git", "rebase", "origin/main"], cwd=mirror, capture_output=True)
    assert (mirror / ".git" / "rebase-merge").is_dir()
    assert lp.main([]) == lp.NOT_SYNCED
    assert "in progress" in capsys.readouterr().err
    subprocess.run(["git", "rebase", "--abort"], cwd=mirror, capture_output=True)


# --- the bookmarked view (LANES-40) ----------------------------------------------

VIEWS = "docs/backlog/INDEX.md\ndocs/backlog/index.html\n"


def _land_issue(lander, issue_id):
    write_issue(lander, "docs/backlog", "CORE", issue_id, "open", "x")
    git("add", "docs/backlog", cwd=lander)
    git("commit", "-q", "-m", issue_id, cwd=lander)
    git("push", "-q", "origin", "main", cwd=lander)
    return f"docs/backlog/CORE/{issue_id}-thing.md"


def test_a_sync_regenerates_the_bookmarked_view_even_when_nothing_is_checked_out(pair, capsys):
    """The sync is no merge and no rewrite, so the view hooks never fire for it; a sync
    the mirror delivered in full checks out nothing at all. The pull regenerates the
    main clone's view itself, so the LANES-11 promise holds for this pull too."""
    origin, lander, mirror = pair
    land(lander, {".gitignore": VIEWS}, "ignore the views")
    _land_issue(lander, "CORE-1")
    assert lp.main([]) == 0                                   # paths checked out
    view = mirror / "docs" / "backlog" / "index.html"
    assert ">CORE-1</a>" in view.read_text(encoding="utf-8")

    rel = _land_issue(lander, "CORE-2")
    deliver(lander, mirror, [rel])                            # the mirror delivered everything
    assert lp.main([]) == 0
    out = capsys.readouterr().out
    assert "0 path(s) checked out" in out and "backlog view refreshed" in out
    page = view.read_text(encoding="utf-8")
    assert ">CORE-2</a>" in page
    assert git("rev-parse", "--short", "HEAD", cwd=mirror) in page   # the header names the new tip


def test_a_repo_without_a_backlog_dir_syncs_silently(pair, capsys):
    origin, lander, mirror = pair
    land(lander, {"fixtures/b.txt": "b\n"})
    assert lp.main([]) == 0
    assert "backlog view" not in capsys.readouterr().out
