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
    assert "close:" in capsys.readouterr().out
    # The close ran off origin/main (LANES-23): the main clone has not pulled it yet,
    # and the throwaway worktree it ran in is gone.
    assert git("log", "-1", "--format=%s", cwd=clone) == "init"
    assert len([l for l in git("worktree", "list", "--porcelain", cwd=clone).splitlines()
                if l.startswith("worktree ")]) == 1


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


def test_the_close_lands_past_unpushed_commits_in_the_main_clone(lane, tmp_path):
    """LANES-23: the shared main clone carries another session's claim, committed and not
    yet pushed (and, for good measure, a local non-backlog commit). The close used to
    refuse on the divergence; it now lands on origin and leaves the clone's commits alone."""
    origin, clone, wt = lane
    _verify_in_the_resolving_commit(wt)
    d = clone / "docs" / "backlog" / "CORE"
    d.mkdir(parents=True)
    (d / "CORE-2-next.md").write_text(ISSUE.replace("CORE-1", "CORE-2").replace("status: verified", "status: open")
                                      .replace("resolution: done", "resolution: null"), encoding="utf-8")
    git("add", "docs/backlog/CORE/CORE-2-next.md", cwd=clone)
    git("commit", "-q", "-m", "docs(backlog): another session's claim", cwd=clone)
    (clone / "local.txt").write_text("unpushed\n", encoding="utf-8")
    git("add", "local.txt", cwd=clone)
    git("commit", "-q", "-m", "local work", cwd=clone)
    head = git("rev-parse", "HEAD", cwd=clone)
    assert ll.main([]) == 0
    assert "status: closed" in _origin_issue(origin, tmp_path)
    assert git("rev-parse", "HEAD", cwd=clone) == head
    assert git("status", "--porcelain", cwd=clone) == ""
    pushed = git("--git-dir", str(origin), "log", "--format=%s", "main", cwd=tmp_path)
    assert "local work" not in pushed and "another session's claim" not in pushed


def test_a_close_that_cannot_push_is_reported_not_fatal(lane, tmp_path, capsys):
    """Origin refuses the close commit: the landing stands, exit 2 names the backstop."""
    origin, clone, wt = lane
    _verify_in_the_resolving_commit(wt)
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nwhile read old new ref; do\n"
                    "  git log --format=%s \"$new\" -1 | grep -q '^docs(backlog): close' && exit 1\n"
                    "done\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    assert ll.main([]) == ll.CLEANUP_INCOMPLETE
    assert "status: verified" in _origin_issue(origin, tmp_path)
    err = capsys.readouterr().err
    assert "backstop" in err and "discarded with the throwaway worktree" in err


# --- an untagged pin does not land (LANES-33) --------------------------------

def _pin(wt, version, subject):
    cfg = wt / ".claude" / "lanes"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(f'plugin_version = "{version}"\n', encoding="utf-8")
    git("add", ".claude/lanes/config.toml", cwd=wt)
    git("commit", "-q", "-m", subject, cwd=wt)


@pytest.fixture
def releases(tmp_path, monkeypatch):
    """The plugin's remote, as a bare repo the release-tag lookup asks; tag(v) publishes one."""
    plugin = tmp_path / "plugin.git"
    git("init", "-q", "--bare", "-b", "next", str(plugin), cwd=tmp_path)
    seed = tmp_path / "plugin-seed"
    git("clone", "-q", str(plugin), str(seed), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=seed)
    git("config", "user.name", "Tester", cwd=seed)
    git("commit", "-q", "--allow-empty", "-m", "lanes", cwd=seed)
    git("push", "-q", "origin", "HEAD:next", cwd=seed)
    monkeypatch.setenv("LANES_RELEASE_REMOTE", str(plugin))
    monkeypatch.setattr(ll, "TAG_WAIT_SECONDS", 0)

    def tag(version):
        git("tag", "-a", f"lanes--v{version}", "-m", f"lanes {version}", cwd=seed)
        git("push", "-q", "origin", f"refs/tags/lanes--v{version}", cwd=seed)
    return tag


def test_a_pin_to_an_untagged_version_is_refused_before_anything_moves(lane, releases, tmp_path, capsys):
    origin, clone, wt = lane
    _pin(wt, "0.9.1", "lanes: pin 0.9.1")
    before = _remote_heads(origin, tmp_path)
    assert ll.main([]) == ll.NOT_LANDED
    assert _remote_heads(origin, tmp_path) == before and wt.is_dir()
    err = capsys.readouterr().err
    assert "lanes--v0.9.1 is not on" in err and "release_tag.py --ensure --push" in err


def test_a_pin_to_a_tagged_version_lands(lane, releases, tmp_path, capsys):
    origin, clone, wt = lane
    releases("0.9.1")
    _pin(wt, "0.9.1", "lanes: pin 0.9.1")
    tip = git("rev-parse", "HEAD", cwd=wt)
    assert ll.main([]) == 0
    assert _remote_heads(origin, tmp_path)["main"] == tip
    assert "pin 0.9.1: lanes--v0.9.1 is on" in capsys.readouterr().out


def test_the_landing_waits_for_the_tag_the_release_ci_mints(lane, releases, monkeypatch):
    """The release reaches `next` seconds before the pin lands; the plugin's CI tags it
    shortly after. The landing polls for the tag instead of refusing at once."""
    origin, clone, wt = lane
    _pin(wt, "0.9.1", "lanes: pin 0.9.1")
    asked = []

    def tag_on_remote(version, remote=None):
        asked.append(version)
        return len(asked) >= 3
    monkeypatch.setattr(ll.rt, "tag_on_remote", tag_on_remote)
    monkeypatch.setattr(ll, "TAG_WAIT_SECONDS", 60)
    monkeypatch.setattr(ll, "TAG_POLL_SECONDS", 0)
    assert ll.main([]) == 0
    assert asked == ["0.9.1"] * 3


def test_a_landing_that_keeps_the_pin_asks_nothing(lane, releases, tmp_path, monkeypatch):
    """Only a landing that MOVES the pin is checked: the pin already on main is not re-litigated."""
    origin, clone, wt = lane
    _pin(clone, "0.9.0", "lanes: pin 0.9.0")                 # untagged, already on main
    git("push", "-q", "origin", "main", cwd=clone)
    git("fetch", "-q", "origin", cwd=wt)
    git("rebase", "-q", "origin/main", cwd=wt)
    git("push", "-q", "-f", "origin", "core-1-work", cwd=wt)
    monkeypatch.setattr(ll.rt, "tag_on_remote", lambda *a, **k: pytest.fail("looked up a pin the lane did not move"))
    assert ll.main([]) == 0


def test_an_unreachable_release_remote_refuses(lane, releases, tmp_path, monkeypatch, capsys):
    origin, clone, wt = lane
    monkeypatch.setenv("LANES_RELEASE_REMOTE", str(tmp_path / "nowhere.git"))
    _pin(wt, "0.9.1", "lanes: pin 0.9.1")
    assert ll.main([]) == ll.NOT_LANDED
    assert "could not be asked" in capsys.readouterr().err


def test_with_the_lookup_off_the_pin_lands_and_says_so(lane, tmp_path, capsys):
    origin, clone, wt = lane                                 # conftest: LANES_RELEASE_REMOTE is empty
    _pin(wt, "0.9.1", "lanes: pin 0.9.1")
    assert ll.main([]) == 0
    assert "release-tag lookup is off" in capsys.readouterr().out
