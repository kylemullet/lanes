"""lanes_land.py: land, verify, and only then clean up (LANES-20).

The incident this guards: a landing that lost the fast-forward race to another
session's push was followed, on the same shell line, by the clean-up -- the worktree
removed and the branch deleted locally and on origin while nothing had landed.
"""
import pytest

import lanes_land as ll
from conftest import git


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """A bare origin, a main clone, and a lane worktree with one pushed commit."""
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    clone = tmp_path / "proj"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    for c in (clone,):
        git("config", "user.email", "t@example.com", cwd=c)
        git("config", "user.name", "Tester", cwd=c)
    (clone / "README.md").write_text("# proj\n", encoding="utf-8")
    git("add", "README.md", cwd=clone)
    git("commit", "-q", "-m", "init", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    wt = tmp_path / "proj-core-1"
    git("worktree", "add", "-q", str(wt), "-b", "core-1-work", cwd=clone)
    (wt / "feature.txt").write_text("x\n", encoding="utf-8")
    git("add", "feature.txt", cwd=wt)
    git("commit", "-q", "-m", "feat: the lane (CORE-1)", cwd=wt)
    git("push", "-q", "-u", "origin", "core-1-work", cwd=wt)
    monkeypatch.chdir(wt)
    return origin, clone, wt


def _remote_heads(origin, tmp_path):
    out = git("ls-remote", "--heads", str(origin), cwd=tmp_path)
    return {line.split("refs/heads/")[1]: line.split()[0] for line in out.splitlines()}


def _race(origin, tmp_path):
    """Another session pushes to origin/main after the lane branched."""
    other = tmp_path / "other"
    git("clone", "-q", str(origin), str(other), cwd=tmp_path)
    git("config", "user.email", "o@example.com", cwd=other)
    git("config", "user.name", "Other", cwd=other)
    (other / "backlog.md").write_text("claim\n", encoding="utf-8")
    git("add", "backlog.md", cwd=other)
    git("commit", "-q", "-m", "docs(backlog): another session's claim", cwd=other)
    git("push", "-q", "origin", "main", cwd=other)


def test_lands_verifies_and_cleans_up(lane, tmp_path, capsys):
    origin, clone, wt = lane
    tip = git("rev-parse", "HEAD", cwd=wt)
    assert ll.main([]) == 0
    heads = _remote_heads(origin, tmp_path)
    assert heads["main"] == tip
    assert "core-1-work" not in heads
    assert not wt.exists()
    assert git("branch", "--list", "core-1-work", cwd=clone) == ""
    assert "landed:" in capsys.readouterr().out


def test_a_lost_fast_forward_race_touches_nothing(lane, tmp_path, capsys):
    origin, clone, wt = lane
    _race(origin, tmp_path)
    before = _remote_heads(origin, tmp_path)
    assert ll.main([]) == ll.NOT_LANDED
    assert _remote_heads(origin, tmp_path) == before        # main not moved, lane branch still on origin
    assert wt.is_dir()                                      # worktree intact
    assert git("branch", "--list", "core-1-work", cwd=clone).strip()  # local branch intact
    err = capsys.readouterr().err
    assert "NOT LANDED" in err and "rebase" in err


def test_keep_lands_and_leaves_the_worktree_and_branch(lane, tmp_path):
    origin, clone, wt = lane
    assert ll.main(["--keep"]) == 0
    heads = _remote_heads(origin, tmp_path)
    assert heads["main"] == git("rev-parse", "HEAD", cwd=wt)
    assert "core-1-work" in heads and wt.is_dir()


def test_dry_run_pushes_and_removes_nothing(lane, tmp_path):
    origin, clone, wt = lane
    before = _remote_heads(origin, tmp_path)
    assert ll.main(["--dry-run"]) == 0
    assert _remote_heads(origin, tmp_path) == before and wt.is_dir()


@pytest.mark.parametrize("dirt", ["untracked.txt", "feature.txt"])
def test_a_dirty_worktree_is_refused_before_anything_moves(lane, tmp_path, dirt):
    origin, clone, wt = lane
    (wt / dirt).write_text("unsaved\n", encoding="utf-8")
    before = _remote_heads(origin, tmp_path)
    assert ll.main([]) == ll.NOT_LANDED
    assert _remote_heads(origin, tmp_path) == before and (wt / dirt).is_file()


def test_refused_from_the_main_clone(lane, monkeypatch, tmp_path, capsys):
    origin, clone, wt = lane
    monkeypatch.chdir(clone)
    assert ll.main([]) == ll.NOT_LANDED
    assert "main clone" in capsys.readouterr().err


def test_refused_on_a_machine_that_does_not_certify(lane, tmp_path, capsys):
    origin, clone, wt = lane
    cfg = wt / ".claude" / "lanes"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text(
        '[[operators]]\nid = "someone-mac"\nshort = "someone"\nname = "Someone"\n'
        'platform = "darwin"\ncertifies = true\n', encoding="utf-8")
    git("add", ".claude/lanes/config.toml", cwd=wt)
    git("commit", "-q", "-m", "config", cwd=wt)
    before = _remote_heads(origin, tmp_path)
    assert ll.main([]) == ll.NOT_LANDED
    assert _remote_heads(origin, tmp_path) == before
    assert "does not certify" in capsys.readouterr().err


def test_onto_lands_on_another_integration_branch(lane, tmp_path):
    origin, clone, wt = lane
    git("push", "-q", "origin", "main:next", cwd=clone)
    git("fetch", "-q", "origin", cwd=wt)
    tip = git("rev-parse", "HEAD", cwd=wt)
    assert ll.main(["--onto", "next"]) == 0
    heads = _remote_heads(origin, tmp_path)
    assert heads["next"] == tip and heads["main"] != tip


def test_a_remote_branch_with_unlanded_commits_is_kept(lane, tmp_path, capsys):
    """Another machine pushed to the topic branch after this one fetched it: the local
    tip lands, the remote branch carries more, so it must not be deleted."""
    origin, clone, wt = lane
    other = tmp_path / "other2"
    git("clone", "-q", "-b", "core-1-work", str(origin), str(other), cwd=tmp_path)
    git("config", "user.email", "o@example.com", cwd=other)
    git("config", "user.name", "Other", cwd=other)
    (other / "more.txt").write_text("more\n", encoding="utf-8")
    git("add", "more.txt", cwd=other)
    git("commit", "-q", "-m", "more work on the lane", cwd=other)
    git("push", "-q", "origin", "core-1-work", cwd=other)
    assert ll.main([]) == ll.CLEANUP_INCOMPLETE
    assert "core-1-work" in _remote_heads(origin, tmp_path)
    assert "carries commits not on origin/main" in capsys.readouterr().err


# --- close the landed issue (LANES-21) --------------------------------------

ISSUE = """---
id: CORE-1
project: CORE
type: story
status: verified
priority: normal
blocked_on: null
assignee: tester
opened: 2026-10-07
closed: null
commit: null
resolution: done
links: []
---

# CORE-1 — the lane

## Context

x

## Current status

Verified.

## Resolution

Shipped by `feat: the lane (CORE-1)`.

Docs: nothing — this increment changed no documented behavior.
"""


def _verify_in_the_resolving_commit(wt):
    """The lane's verify rides in its resolving commit, as worktree-increment step 9 says."""
    d = wt / "docs" / "backlog" / "CORE"
    d.mkdir(parents=True)
    (d / "CORE-1-the-lane.md").write_text(ISSUE, encoding="utf-8")
    git("add", "docs/backlog/CORE/CORE-1-the-lane.md", cwd=wt)
    git("commit", "-q", "--amend", "--no-edit", cwd=wt)
    git("push", "-q", "-f", "origin", "core-1-work", cwd=wt)


def _origin_issue(origin, tmp_path):
    return git("--git-dir", str(origin), "show", "main:docs/backlog/CORE/CORE-1-the-lane.md", cwd=tmp_path)


def test_landing_closes_the_landed_issue_on_origin(lane, tmp_path, capsys):
    origin, clone, wt = lane
    _verify_in_the_resolving_commit(wt)
    tip = git("rev-parse", "--short=7", "HEAD", cwd=wt)
    assert ll.main([]) == 0
    text = _origin_issue(origin, tmp_path)
    assert "status: closed" in text and f"commit: {tip}" in text
    assert git("--git-dir", str(origin), "log", "-1", "--format=%s", "main", cwd=tmp_path).startswith(
        "docs(backlog): close CORE-1")
    assert git("rev-parse", "HEAD", cwd=clone) == git("--git-dir", str(origin), "rev-parse", "main", cwd=tmp_path)
    assert "close:" in capsys.readouterr().out


def test_no_close_leaves_the_issue_verified(lane, tmp_path):
    origin, clone, wt = lane
    _verify_in_the_resolving_commit(wt)
    assert ll.main(["--no-close"]) == 0
    assert "status: verified" in _origin_issue(origin, tmp_path)


def test_keep_still_closes_the_landed_issue(lane, tmp_path):
    origin, clone, wt = lane
    _verify_in_the_resolving_commit(wt)
    assert ll.main(["--keep"]) == 0
    assert "status: closed" in _origin_issue(origin, tmp_path) and wt.is_dir()


def test_a_close_that_cannot_push_is_reported_not_fatal(lane, tmp_path, capsys):
    """The main clone carries a local non-backlog commit: the backfill keeps its close
    local (it needs the operator's OK), so the landing reports exit 2, not a failure."""
    origin, clone, wt = lane
    _verify_in_the_resolving_commit(wt)
    (clone / "local.txt").write_text("unpushed\n", encoding="utf-8")
    git("add", "local.txt", cwd=clone)
    git("commit", "-q", "-m", "local work", cwd=clone)
    assert ll.main([]) == ll.CLEANUP_INCOMPLETE
    assert "status: verified" in _origin_issue(origin, tmp_path)
    assert "backstop" in capsys.readouterr().err
