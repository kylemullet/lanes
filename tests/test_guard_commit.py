"""The commit guard (LANES-1): the position rule at git's pre-commit, over the staged set."""
import shutil
import subprocess
from pathlib import Path

import pytest

import guard_commit as gc
import guard_position as gp
import lanes_doctor as doc
from conftest import git

RULES = gp.Rules("main", ("docs/", ".claude/lanes/", "*.md"))
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="sh not on PATH")


def _where(toplevel="/r", main_clone="/r", branch="main"):
    return gc.Where(toplevel=toplevel, main_clone=main_clone, branch=branch, git_dir=f"{main_clone}/.git")


# --- the truth table, pure ---------------------------------------------------------

def test_lane_commit_is_allowed_whatever_it_stages():
    assert gc.decide(["src/x.py"], _where(toplevel="/r-lane", branch="lane-work"), RULES)[0] == gc.ALLOW


def test_main_direct_commit_on_main_in_the_main_clone_is_allowed():
    assert gc.decide(["docs/backlog/A-1.md", "README.md", ".claude/lanes/config.toml"], _where(), RULES)[0] == gc.ALLOW


def test_empty_commit_on_main_is_allowed():
    assert gc.decide([], _where(), RULES)[0] == gc.ALLOW


def test_code_on_main_in_the_main_clone_is_refused_and_named():
    code, why = gc.decide(["docs/a.md", "src/x.py", "tests/test_x.py"], _where(), RULES)
    assert code == gc.BLOCK
    assert "src/x.py" in why and "tests/test_x.py" in why and "docs/a.md" not in why.split("Main-direct")[0]
    assert "git worktree add" in why and "--no-verify" in why


def test_a_long_refusal_is_truncated():
    staged = [f"src/m{i}.py" for i in range(20)]
    why = gc.decide(staged, _where(), RULES)[1]
    assert "and 12 more" in why


def test_a_nested_md_is_not_main_direct():
    """`*.md` is root-level only: `src/notes.md` is code-tree work."""
    assert gc.decide(["src/notes.md"], _where(), RULES)[0] == gc.BLOCK


def test_main_clone_off_main_is_refused_even_for_docs():
    """The 2026-09-10 shape: another lane's branch checked out in the main clone."""
    code, why = gc.decide(["docs/a.md"], _where(branch="other-work"), RULES)
    assert code == gc.BLOCK and "`other-work`" in why
    assert gc.decide(["docs/a.md"], _where(branch="HEAD"), RULES)[0] == gc.BLOCK


def test_worktree_on_main_is_refused():
    assert gc.decide(["docs/a.md"], _where(toplevel="/r-lane", branch="main"), RULES)[0] == gc.BLOCK


def test_configured_main_branch_is_the_one_judged():
    rules = gp.Rules("trunk", ("docs/",))
    assert gc.decide(["src/x.py"], _where(branch="trunk"), rules)[0] == gc.BLOCK
    assert gc.decide(["src/x.py"], _where(branch="main"), rules)[0] == gc.BLOCK   # main clone off trunk


def test_shim_is_lf_and_names_the_launcher(tmp_path):
    text = gc.shim_text(Path("/opt/it's here/lanes.sh"))
    assert text.startswith("#!/bin/sh\n") and "\r" not in text
    assert gc.SHIM_MARKER in text
    assert "guard_commit.py --hook" in text
    assert "'/opt/it'\"'\"'s here/lanes.sh'" in text, "the path is single-quoted, quotes escaped"


# --- real git ------------------------------------------------------------------------

def _commit(cwd, *paths, verify=True, msg="m"):
    for p in paths:
        f = Path(cwd) / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"{p} {f.stat().st_mtime_ns if f.exists() else 0}\n", encoding="utf-8")
    subprocess.run(["git", "add", *paths], cwd=cwd, check=True, capture_output=True)
    args = ["git", "commit", "-q", "-m", msg] + ([] if verify else ["--no-verify"])
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


@needs_git
@needs_sh
def test_installed_shim_enforces_the_rule_through_git(repo, tmp_path):
    code, line = gc.install(str(repo))
    assert code == 0 and "installed at" in line
    assert gc.status(str(repo))[0] == "installed"

    assert _commit(repo, "docs/a.md").returncode == 0                       # a claim's shape
    done = _commit(repo, "src/x.py")                                        # code on main
    assert done.returncode != 0 and "lanes commit guard" in done.stderr
    git("reset", "-q", cwd=repo)
    assert _commit(repo, "src/x.py", verify=False).returncode == 0          # the bypass

    lane = tmp_path / "proj-lane"
    git("worktree", "add", "-q", str(lane), "-b", "lane-work", cwd=repo)
    assert _commit(lane, "src/y.py").returncode == 0                        # a lane, same hooks dir

    git("checkout", "-q", "--detach", cwd=lane)
    git("checkout", "-q", "lane-work", cwd=repo)
    done = _commit(repo, "docs/b.md")                                       # the incident shape
    assert done.returncode != 0 and "`lane-work`" in done.stderr


@needs_git
@needs_sh
def test_commit_during_a_rebase_on_main_is_judged_as_main(repo, tmp_path):
    """A conflicted `pull --rebase` in the main clone detaches HEAD; resolving and
    committing a docs file is still a main-direct commit on main, not 'detached'."""
    gc.install(str(repo))
    git("checkout", "-q", "-b", "side", cwd=repo)
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "c.md").write_text("side\n", encoding="utf-8")
    git("add", "docs/c.md", cwd=repo)
    git("commit", "-q", "--no-verify", "-m", "side", cwd=repo)
    git("checkout", "-q", "main", cwd=repo)
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "c.md").write_text("main\n", encoding="utf-8")
    git("add", "docs/c.md", cwd=repo)
    git("commit", "-q", "-m", "main", cwd=repo)
    stopped = subprocess.run(["git", "rebase", "side"], cwd=repo, capture_output=True, text=True)
    assert stopped.returncode != 0, "the rebase must stop on the conflict for this test to mean anything"
    w = gc.where(str(repo))
    assert w.branch == "main"
    (repo / "docs" / "c.md").write_text("resolved\n", encoding="utf-8")
    git("add", "docs/c.md", cwd=repo)
    assert gc.evaluate(str(repo))[0] == gc.ALLOW
    git("rebase", "--abort", cwd=repo)


@needs_git
def test_install_is_idempotent_and_repoints(repo, tmp_path):
    assert "installed at" in gc.install(str(repo))[1]
    assert gc.install(str(repo)) == (0, "commit guard: installed (unchanged)")
    other = tmp_path / "elsewhere" / "lanes.sh"
    assert gc.status(str(repo), other)[0] == "stale"
    code, line = gc.install(str(repo), other)
    assert code == 0 and "re-pointed" in line
    assert gc.status(str(repo), other)[0] == "installed"


@needs_git
@needs_sh
def test_a_vanished_launcher_allows_and_says_so(repo, tmp_path):
    gc.install(str(repo), tmp_path / "gone" / "lanes.sh")
    done = _commit(repo, "src/x.py")
    assert done.returncode == 0
    assert "is gone" in done.stderr


@needs_git
def test_a_foreign_pre_commit_is_never_overwritten(repo):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    code, line = gc.install(str(repo))
    assert code == 1 and "another tool's" in line
    assert hook.read_text(encoding="utf-8") == "#!/bin/sh\necho mine\n"
    assert gc.status(str(repo))[0] == "foreign"


@needs_git
def test_core_hookspath_is_left_alone(repo):
    git("config", "core.hooksPath", ".githooks", cwd=repo)
    code, line = gc.install(str(repo))
    assert code == 1 and "core.hooksPath" in line
    assert not (repo / ".githooks").exists()
    assert gc.status(str(repo))[0] == "hookspath"


@needs_git
def test_commit_guard_false_turns_it_off_and_removes_the_shim(repo):
    gc.install(str(repo))
    cfg = repo / ".claude" / "lanes" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("[git]\ncommit_guard = false\n", encoding="utf-8")
    assert gc.status(str(repo))[0] == "stale"
    code, line = gc.install(str(repo))
    assert code == 0 and "removed" in line
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()
    assert gc.status(str(repo))[0] == "disabled"
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("x\n", encoding="utf-8")
    git("add", "src/x.py", cwd=repo)
    assert gc.evaluate(str(repo))[0] == gc.ALLOW


@needs_git
def test_install_from_a_worktree_writes_the_shared_hook(repo, tmp_path):
    lane = tmp_path / "proj-lane"
    git("worktree", "add", "-q", str(lane), "-b", "lane-work", cwd=repo)
    assert gc.main(["--install", "--root", str(lane)]) == 0
    assert (repo / ".git" / "hooks" / "pre-commit").is_file()


@needs_git
def test_doctor_reports_the_shim(repo):
    assert doc.check_commit_guard(repo).status == doc.WARN
    assert "guard_commit.py --install" in doc.check_commit_guard(repo).detail
    gc.install(str(repo))
    assert doc.check_commit_guard(repo).status == doc.OK
