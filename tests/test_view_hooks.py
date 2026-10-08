"""The bookmarked view (LANES-11): git hooks that refresh it after a pull, chained after
another tool's hooks, and the refresh every backlog write makes."""
import shutil
from pathlib import Path

import pytest

import backlog_index as bidx
import lanes_doctor as doc
import view_hooks as vh
from conftest import git, write_issue

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="sh not on PATH")

LFS = ('#!/bin/sh\ncommand -v git-lfs >/dev/null 2>&1 || { echo missing >&2; exit 2; }\n'
       'git lfs post-checkout "$@"\n')
VIEWS = "docs/backlog/INDEX.md\ndocs/backlog/index.html\n"


def _hook(repo, name):
    return repo / ".git" / "hooks" / name


def _config(repo, text):
    (repo / ".claude" / "lanes").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "lanes" / "config.toml").write_text(text, encoding="utf-8")


def test_block_names_the_launcher_and_never_fails_the_git_command():
    b = vh.block("post-merge", Path("/p/lanes.sh"))
    assert b.startswith(vh.BEGIN) and b.rstrip().endswith(vh.END)
    assert "lanes_view='/p/lanes.sh'" in b and "--hook post-merge" in b and b.rstrip("\n").splitlines()[-2].endswith("|| true")


@needs_git
def test_install_writes_all_three_hooks_and_is_idempotent(repo, tmp_path):
    code, line = vh.install(str(repo))
    assert code == 0 and line.startswith("view hooks: installed")
    for name in vh.HOOKS:
        text = _hook(repo, name).read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh\n") and text.count(vh.BEGIN) == 1
    assert vh.status(str(repo))[0] == "installed"
    assert vh.install(str(repo)) == (0, "view hooks: installed (unchanged)")
    code, line = vh.install(str(repo), launcher=tmp_path / "other" / "lanes.sh")
    assert code == 0 and "re-pointed" in line
    assert vh.status(str(repo))[0] == "stale"          # against the real launcher: another path


@needs_git
def test_install_chains_after_another_tools_hook(repo):
    _hook(repo, "post-checkout").write_text(LFS, encoding="utf-8")
    assert vh.install(str(repo))[0] == 0
    text = _hook(repo, "post-checkout").read_text(encoding="utf-8")
    assert text.startswith(LFS) and text.count(vh.BEGIN) == 1     # git-lfs keeps its lines, first
    assert vh.install(str(repo)) == (0, "view hooks: installed (unchanged)")
    assert _hook(repo, "post-checkout").read_text(encoding="utf-8").count(vh.BEGIN) == 1


@needs_git
@pytest.mark.parametrize("text,why", [
    ('#!/bin/sh\nexec other-tool "$@"\n', "exec"),
    ("#!/usr/bin/env python3\nprint('x')\n", "not a shell script"),
])
def test_a_hook_that_cannot_take_the_block_is_left_alone(repo, text, why):
    _hook(repo, "post-merge").write_text(text, encoding="utf-8")
    code, line = vh.install(str(repo))
    assert code == 1 and why in line and "post-merge" in line
    assert _hook(repo, "post-merge").read_text(encoding="utf-8") == text
    assert vh.status(str(repo))[0] == "foreign"


@needs_git
def test_env_bash_shebang_chains(repo):
    _hook(repo, "post-merge").write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
    assert vh.install(str(repo))[0] == 0
    assert vh.BEGIN in _hook(repo, "post-merge").read_text(encoding="utf-8")


@needs_git
def test_core_hookspath_is_left_alone(repo):
    git("config", "core.hooksPath", ".husky", cwd=repo)
    code, line = vh.install(str(repo))
    assert code == 1 and "core.hooksPath" in line
    assert vh.status(str(repo))[0] == "hookspath"


@needs_git
def test_serve_mode_turns_the_hooks_off_and_removes_only_the_blocks(repo):
    _hook(repo, "post-checkout").write_text(LFS, encoding="utf-8")
    vh.install(str(repo))
    _config(repo, '[backlog]\nview_mode = "serve"\n')
    code, line = vh.install(str(repo))
    assert code == 0 and "removed" in line
    assert _hook(repo, "post-checkout").read_text(encoding="utf-8") == LFS     # git-lfs untouched
    assert not _hook(repo, "post-merge").exists()                              # ours alone: gone
    assert vh.status(str(repo))[0] == "disabled"


@needs_git
def test_the_hook_ignores_a_worktree_and_a_mid_rebase_checkout(repo, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bidx, "refresh_main_view", lambda auto=True: calls.append(1))
    lane = tmp_path / "proj-lane"
    git("worktree", "add", "-q", str(lane), "-b", "lane-work", cwd=repo)
    assert vh.run_hook(str(lane), "post-checkout", ["0" * 40, "a" * 40, "1"]) == 0 and calls == []
    assert vh.run_hook(str(repo), "post-checkout", ["a", "b", "0"]) == 0 and calls == []   # a file checkout
    (repo / ".git" / "rebase-merge").mkdir()
    assert vh.run_hook(str(repo), "post-checkout", ["a", "b", "1"]) == 0 and calls == []
    (repo / ".git" / "rebase-merge").rmdir()
    assert vh.run_hook(str(repo), "post-checkout", ["a", "b", "1"]) == 0 and calls == [1]
    assert vh.run_hook(str(repo), "post-merge", ["0"]) == 0 and calls == [1, 1]


@needs_git
@needs_sh
def test_a_pull_refreshes_the_main_clones_view_through_git(repo, tmp_path):
    """End to end: the installed hooks, run by git itself, on a fast-forward pull and on a
    pull that rebases a local commit."""
    (repo / ".gitignore").write_text(VIEWS, encoding="utf-8")
    write_issue(repo, "docs/backlog", "CORE", "CORE-1", "open", "x")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "CORE-1", cwd=repo)
    origin = tmp_path / "origin.git"
    git("clone", "-q", "--bare", str(repo), str(origin), cwd=tmp_path)
    git("remote", "add", "origin", str(origin), cwd=repo)
    git("fetch", "-q", "origin", cwd=repo)
    git("branch", "-q", "-u", "origin/main", cwd=repo)
    other = tmp_path / "other"
    git("clone", "-q", str(origin), str(other), cwd=tmp_path)
    for c in (other,):
        git("config", "user.email", "t@example.com", cwd=c)
        git("config", "user.name", "Tester", cwd=c)
    assert vh.install(str(repo))[0] == 0
    view = repo / "docs" / "backlog" / "index.html"

    write_issue(other, "docs/backlog", "CORE", "CORE-2", "open", "x")
    git("add", ".", cwd=other)
    git("commit", "-q", "-m", "CORE-2", cwd=other)
    git("push", "-q", "origin", "HEAD:main", cwd=other)
    git("pull", "-q", "--rebase", cwd=repo)                      # fast-forward: post-merge
    assert ">CORE-2</a>" in view.read_text(encoding="utf-8")

    write_issue(other, "docs/backlog", "CORE", "CORE-3", "open", "x")
    git("add", ".", cwd=other)
    git("commit", "-q", "-m", "CORE-3", cwd=other)
    git("push", "-q", "origin", "HEAD:main", cwd=other)
    (repo / "docs" / "local.md").parent.mkdir(exist_ok=True)
    (repo / "docs" / "local.md").write_text("x\n", encoding="utf-8")
    git("add", "docs/local.md", cwd=repo)
    git("commit", "-q", "-m", "local", cwd=repo)
    git("pull", "-q", "--rebase", cwd=repo)                      # a real rebase: post-rewrite
    page = view.read_text(encoding="utf-8")
    assert ">CORE-3</a>" in page
    assert git("rev-parse", "--short", "HEAD", cwd=repo) in page     # the stamp names the commit

    lane = tmp_path / "proj-lane"
    git("worktree", "add", "-q", str(lane), "-b", "lane-work", cwd=repo)
    assert not (lane / "docs" / "backlog" / "index.html").exists()   # never a worktree's copy


@needs_git
def test_doctor_reports_the_view_hooks(repo):
    assert doc.check_view_hooks(repo).status == doc.WARN
    assert "view_hooks.py --install" in doc.check_view_hooks(repo).detail
    vh.install(str(repo))
    assert doc.check_view_hooks(repo).status == doc.OK
    _config(repo, '[backlog]\nview_mode = "serve"\n')
    vh.install(str(repo))
    assert doc.check_view_hooks(repo).status == doc.OK
