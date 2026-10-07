"""Guards ``scripts/guard_position.py`` -- the lanes position-guard ``PreToolUse`` hook.

`worktree-increment` step 0 requires, before any write that is not the claim, that
the checkout is NOT the main clone AND the branch is NOT the main branch. The hook
enforces it mechanically on the four edit tools. These tests pin:

* **the truth table**, cell by cell, through the FAKE environment the script
  exposes (``LANES_GUARD_*``) -- no real git state. The critical cell is (main
  clone, NOT main): the 2026-09-10 incident shape, which an AND-form would allow;
* **the hook contract** -- JSON on stdin, exit 2 + stderr to block, exit 0 to
  allow, fail OPEN on garbage input, tools other than the four pass through;
* **the config binding** -- `git.main_branch` and `git.main_direct_paths` come from
  the TARGET repo's `.claude/lanes/config.toml`, defaults otherwise;
* **the foreign-repo rule** -- a target whose main clone is not the session's
  (`$CLAUDE_PROJECT_DIR`) is allowed: another repo's main branch is not a landing
  path of this one;
* **the wiring** -- ``hooks/hooks.json`` carries the hook with the right matcher.

Integration tests build throwaway repos + worktrees and run the REAL git path.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "guard_position.py"
HOOKS = REPO / "hooks" / "hooks.json"


def _load():
    spec = importlib.util.spec_from_file_location("guard_position", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # dataclasses resolves postponed annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


gp = _load()


def _fake_env(tmp_path, *, in_main_clone, branch, ignored=(), main_branch=None, main_direct=(), project=None):
    """A repo layout the script never has to touch: paths only."""
    main_clone = tmp_path / "proj"
    lane = tmp_path / "proj-lane"
    toplevel = main_clone if in_main_clone else lane
    env = {
        gp.ENV_TOPLEVEL: str(toplevel),
        gp.ENV_MAIN_CLONE: str(main_clone),
        gp.ENV_BRANCH: branch,
        gp.ENV_IGNORED: os.pathsep.join(ignored),
        gp.ENV_MAIN_BRANCH: main_branch or "",
        gp.ENV_MAIN_DIRECT: os.pathsep.join(main_direct),
        gp.ENV_PROJECT_MAIN_CLONE: str(project) if project else "",
    }
    return env, toplevel


def _payload(path, tool="Edit", key="file_path"):
    return {"tool_name": tool, "tool_input": {key: str(path)}}


def _run(payload, env_overrides, stdin=None):
    env = dict(os.environ)
    env.pop("PYTHONWARNINGS", None)
    env.pop(gp.ENV_PROJECT_DIR, None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload) if stdin is None else stdin,
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(REPO),
    )


# --- the main-direct set -------------------------------------------------------

@pytest.mark.parametrize("rel", ["docs/backlog/INFRA/INFRA-60.md", "docs/STATE.md", "CLAUDE.md", "README.md", "./docs/x.md",
                                 ".claude/lanes/config.toml", ".claude/lanes/preflight.md"])
def test_default_main_direct_paths(rel):
    assert gp.is_main_direct(rel)


@pytest.mark.parametrize("rel", [
    "modules/dwg_io.py", "scripts/guard_position.py", "tests/test_guard_position.py",
    ".claude/settings.json",          # the hook's own wiring is NOT main-direct
    ".claude/skills/x/SKILL.md",      # not in the DEFAULT list; a project adds it
    ".github/workflows/test.yml", "frontend/src/App.jsx", "requirements.txt", ".gitignore",
    "modules/README.md",              # *.md is a ROOT glob, not a repo-wide one
    "docs",                           # the directory itself, no trailing slash
])
def test_not_main_direct_by_default(rel):
    assert not gp.is_main_direct(rel)


def test_configured_main_direct_entries_have_three_shapes():
    cfg = ("docs/", "drive/", ".claude/skills/", "*.md", "mkdocs.yml")
    for rel in ("drive/x/notes.md", ".claude/skills/a/SKILL.md", "mkdocs.yml", "docs\\x.md"):
        assert gp.is_main_direct(rel, cfg), rel
    for rel in ("mkdocs.yml.bak", "src/mkdocs.yml", ".claude/settings.json"):
        assert not gp.is_main_direct(rel, cfg), rel


def test_rules_come_from_the_target_repos_config(tmp_path):
    (tmp_path / ".claude" / "lanes").mkdir(parents=True)
    (tmp_path / ".claude" / "lanes" / "config.toml").write_text(
        '[git]\nmain_branch = "trunk"\nmain_direct_paths = ["docs/", "notes/", "*.md"]\n', encoding="utf-8")
    rules = gp.rules_for(str(tmp_path), env={})
    assert rules.main_branch == "trunk" and rules.main_direct == ("docs/", "notes/", "*.md")
    assert gp.rules_for(str(tmp_path / "nowhere"), env={}) == gp.Rules("main", ("docs/", ".claude/lanes/", "*.md"))
    (tmp_path / ".claude" / "lanes" / "config.toml").write_text("not toml [", encoding="utf-8")
    assert gp.rules_for(str(tmp_path), env={}) == gp.Rules("main", ("docs/", ".claude/lanes/", "*.md"))


# --- the truth table -----------------------------------------------------------

TRUTH_TABLE = [
    # (in_main_clone, branch, rel path, expected)
    (False, "infra-60-work", "modules/dwg_io.py", gp.ALLOW),            # a lane
    (False, "infra-60-work", "docs/backlog/x.md", gp.ALLOW),            # a lane, docs too
    (False, "HEAD", "modules/dwg_io.py", gp.ALLOW),                     # detached (the canary worktree)
    (True, "main", "docs/backlog/INFRA/INFRA-60.md", gp.ALLOW),         # THE claim
    (True, "main", "CLAUDE.md", gp.ALLOW),
    (True, "main", "modules/dwg_io.py", gp.BLOCK),                      # code on main
    (True, "main", ".claude/settings.json", gp.BLOCK),
    (True, "main", "tests/test_x.py", gp.BLOCK),
    (True, "infra-60-work", "docs/backlog/x.md", gp.BLOCK),             # 2026-09-10: docs in main clone on a lane branch
    (True, "infra-60-work", "modules/dwg_io.py", gp.BLOCK),
    (True, "HEAD", "docs/backlog/x.md", gp.BLOCK),                      # main clone detached
    (False, "main", "docs/backlog/x.md", gp.BLOCK),                     # a worktree sitting on main
    (False, "main", "modules/dwg_io.py", gp.BLOCK),
]


@pytest.mark.parametrize("in_main_clone,branch,rel,expected", TRUTH_TABLE)
def test_truth_table_in_process(tmp_path, in_main_clone, branch, rel, expected):
    env, toplevel = _fake_env(tmp_path, in_main_clone=in_main_clone, branch=branch)
    code, why = gp.evaluate(_payload(toplevel / rel), env)
    assert code == expected, why
    if expected == gp.BLOCK:
        assert "lanes position guard" in why


@pytest.mark.parametrize("in_main_clone,branch,rel,expected", TRUTH_TABLE)
def test_truth_table_through_the_hook_contract(tmp_path, in_main_clone, branch, rel, expected):
    """The real child process: exit 2 + stderr blocks, exit 0 allows, stdout silent."""
    env, toplevel = _fake_env(tmp_path, in_main_clone=in_main_clone, branch=branch)
    done = _run(_payload(toplevel / rel), env)
    assert done.returncode == expected, done.stderr
    if expected == gp.BLOCK:
        assert "Blocked by the lanes position guard" in done.stderr
    else:
        assert done.stderr == ""
    assert done.stdout == ""


def test_the_incident_cell_is_the_reason_for_either_not_both(tmp_path):
    """Main clone + another lane's branch + a docs-only write: the 2026-09-10 shape.

    An AND-form (main clone AND main) ALLOWS this cell. If this test ever passes
    with ALLOW, the hook has been weakened.
    """
    env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch="ui-55-work")
    code, why = gp.evaluate(_payload(toplevel / "docs/backlog/UI/UI-55.md"), env)
    assert code == gp.BLOCK
    assert "2026-09-10" in why and "ui-55-work" in why


def test_configured_main_branch_and_main_direct_drive_the_table(tmp_path):
    env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch="trunk", main_branch="trunk",
                              main_direct=("docs/", ".claude/skills/", "*.md"))
    assert gp.evaluate(_payload(toplevel / ".claude/skills/x/SKILL.md"), env)[0] == gp.ALLOW   # a skill edit at closeout
    assert gp.evaluate(_payload(toplevel / "src/x.py"), env)[0] == gp.BLOCK
    env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch="main", main_branch="trunk")
    code, why = gp.evaluate(_payload(toplevel / "docs/x.md"), env)
    assert code == gp.BLOCK and "`trunk`" in why       # `main` is just another branch in this repo


def test_a_foreign_repository_is_allowed_whatever_its_state(tmp_path):
    """The session's repo is elsewhere: another repo's main branch is not our landing path."""
    other = tmp_path / "other-project"
    for branch, rel in (("main", "src/x.py"), ("main", "docs/x.md"), ("lane", "src/x.py")):
        env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch=branch, project=other)
        code, why = gp.evaluate(_payload(toplevel / rel), env)
        assert code == gp.ALLOW and "foreign repository" in why, (branch, rel, why)
    # the SAME repo as the session's is judged
    env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch="main", project=tmp_path / "proj")
    assert gp.evaluate(_payload(toplevel / "src/x.py"), env)[0] == gp.BLOCK
    # no project dir known: judged (fail toward the rule, not open)
    env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch="main")
    assert gp.evaluate(_payload(toplevel / "src/x.py"), env)[0] == gp.BLOCK


# --- pass-throughs -------------------------------------------------------------

@pytest.mark.parametrize("tool", ["Bash", "Read", "Glob", "Grep", "Agent", "WebFetch", None])
def test_non_edit_tools_pass(tmp_path, tool):
    env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch="main")
    payload = {"tool_name": tool, "tool_input": {"file_path": str(toplevel / "modules/x.py")}}
    assert gp.evaluate(payload, env)[0] == gp.ALLOW


@pytest.mark.parametrize("tool", gp.EDIT_TOOLS)
def test_every_edit_tool_is_guarded(tmp_path, tool):
    env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch="main")
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    assert gp.evaluate(_payload(toplevel / "modules/x.py", tool=tool, key=key), env)[0] == gp.BLOCK


def test_notebook_edit_reads_either_path_key(tmp_path):
    env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch="main")
    for key in ("notebook_path", "file_path"):
        assert gp.evaluate(_payload(toplevel / "modules/x.ipynb", tool="NotebookEdit", key=key), env)[0] == gp.BLOCK


def test_missing_or_blank_path_passes(tmp_path):
    env, _ = _fake_env(tmp_path, in_main_clone=True, branch="main")
    assert gp.evaluate({"tool_name": "Edit", "tool_input": {}}, env)[0] == gp.ALLOW
    assert gp.evaluate({"tool_name": "Edit", "tool_input": {"file_path": "  "}}, env)[0] == gp.ALLOW
    assert gp.evaluate({"tool_name": "Edit"}, env)[0] == gp.ALLOW
    assert gp.evaluate({"tool_name": "Edit", "tool_input": "not a dict"}, env)[0] == gp.ALLOW


def test_target_outside_the_repo_passes(tmp_path):
    """Memory files, the scratchpad, /tmp: not this guard's business."""
    env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch="main")
    outside = tmp_path / "elsewhere" / "memory.md"
    assert gp.evaluate(_payload(outside), env)[0] == gp.ALLOW
    # a sibling whose name merely STARTS with the toplevel's name is outside too
    sibling = Path(str(toplevel) + "-lane") / "modules" / "x.py"
    assert gp.relative_to_toplevel(str(sibling), str(toplevel)) is None


def test_ignored_paths_pass(tmp_path):
    """An ignored file can never reach a commit, so the rule has nothing to protect."""
    env, toplevel = _fake_env(
        tmp_path, in_main_clone=True, branch="main",
        ignored=(".claude/settings.local.json", "frontend/dist/index.html"),
    )
    assert gp.evaluate(_payload(toplevel / ".claude/settings.local.json"), env)[0] == gp.ALLOW
    assert gp.evaluate(_payload(toplevel / "frontend/dist/index.html"), env)[0] == gp.ALLOW
    assert gp.evaluate(_payload(toplevel / ".claude/settings.json"), env)[0] == gp.BLOCK


@pytest.mark.parametrize("stdin", ["", "   ", "not json", "[1, 2]", '"a string"'])
def test_garbage_stdin_fails_open(tmp_path, stdin):
    env, _ = _fake_env(tmp_path, in_main_clone=True, branch="main")
    done = _run({}, env, stdin=stdin)
    assert done.returncode == gp.ALLOW, done.stderr
    assert done.stdout == ""


def test_explain_mode(tmp_path):
    env, toplevel = _fake_env(tmp_path, in_main_clone=True, branch="main")
    e = dict(os.environ, **env)
    e.pop("PYTHONWARNINGS", None)
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--explain", str(toplevel / "modules/x.py")],
        capture_output=True, text=True, encoding="utf-8", env=e, cwd=str(REPO),
    )
    assert done.returncode == gp.BLOCK
    assert done.stdout.startswith("BLOCK: ")


# --- the real git path ---------------------------------------------------------

def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True,
        text=True, encoding="utf-8",
    ).stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_real_repo_and_worktree(tmp_path):
    """The `--git-common-dir` arithmetic against a real main clone + worktree."""
    main_clone = tmp_path / "proj"
    main_clone.mkdir()
    _git("init", "-q", "-b", "main", cwd=main_clone)
    _git("config", "user.email", "t@example.com", cwd=main_clone)
    _git("config", "user.name", "t", cwd=main_clone)
    (main_clone / "docs").mkdir()
    (main_clone / "docs" / "a.md").write_text("a\n", encoding="utf-8")
    (main_clone / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    _git("add", "-A", cwd=main_clone)
    _git("commit", "-q", "-m", "init", cwd=main_clone)
    lane = tmp_path / "proj-lane"
    _git("worktree", "add", "-q", str(lane), "-b", "lane-work", cwd=main_clone)

    env = {k: "" for k in (gp.ENV_TOPLEVEL, gp.ENV_MAIN_CLONE, gp.ENV_BRANCH, gp.ENV_IGNORED,
                            gp.ENV_PROJECT_MAIN_CLONE, gp.ENV_MAIN_BRANCH, gp.ENV_MAIN_DIRECT)}

    pos = gp.position_of(str(main_clone / "docs" / "a.md"), env)
    assert pos.in_main_clone and pos.on_main_branch
    pos = gp.position_of(str(lane / "docs" / "a.md"), env)
    assert not pos.in_main_clone and pos.branch == "lane-work"
    # a file in a directory that does not exist yet still resolves to its checkout
    pos = gp.position_of(str(lane / "new" / "deeper" / "x.py"), env)
    assert not pos.in_main_clone and pos.branch == "lane-work"

    # the four cells that matter, through the real path
    assert gp.evaluate(_payload(main_clone / "docs" / "a.md"), env)[0] == gp.ALLOW      # claim
    assert gp.evaluate(_payload(main_clone / "code.py"), env)[0] == gp.BLOCK            # code on main
    assert gp.evaluate(_payload(lane / "code.py"), env)[0] == gp.ALLOW                  # lane
    assert gp.evaluate(_payload(main_clone / "ignored.txt"), env)[0] == gp.ALLOW        # ignored
    assert gp.evaluate(_payload(tmp_path / "outside.py"), env)[0] == gp.ALLOW           # no repo

    # the incident cell: main clone with the lane's branch checked out
    _git("checkout", "-q", "--detach", cwd=lane)          # free the branch name
    _git("checkout", "-q", "lane-work", cwd=main_clone)
    assert gp.evaluate(_payload(main_clone / "docs" / "a.md"), env)[0] == gp.BLOCK
    _git("checkout", "-q", "main", cwd=main_clone)

    # the foreign-repo rule through real git: a SECOND repo on its main branch
    other = tmp_path / "other"
    other.mkdir()
    _git("init", "-q", "-b", "main", cwd=other)
    _git("config", "user.email", "t@example.com", cwd=other)
    _git("config", "user.name", "t", cwd=other)
    (other / "x.py").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=other)
    _git("commit", "-q", "-m", "init", cwd=other)
    session_env = dict(env, **{gp.ENV_PROJECT_DIR: str(main_clone)})
    assert gp.evaluate(_payload(other / "y.py"), session_env)[0] == gp.ALLOW            # foreign
    assert gp.evaluate(_payload(main_clone / "code.py"), session_env)[0] == gp.BLOCK    # ours, still judged
    # a session started in the WORKTREE still owns the main clone's repo
    lane_env = dict(env, **{gp.ENV_PROJECT_DIR: str(lane)})
    assert gp.evaluate(_payload(main_clone / "code.py"), lane_env)[0] == gp.BLOCK
    assert gp.evaluate(_payload(other / "y.py"), lane_env)[0] == gp.ALLOW
    # config in the target repo changes the rules through the real path
    (other / ".claude" / "lanes").mkdir(parents=True)
    (other / ".claude" / "lanes" / "config.toml").write_text('[git]\nmain_branch = "dev"\n', encoding="utf-8")
    assert gp.evaluate(_payload(other / "y.py"), env)[0] == gp.BLOCK      # on `main`, not the main clone's `dev`... a worktree? no: main clone on a non-main branch


# --- the wiring ----------------------------------------------------------------

def test_hooks_json_wires_the_hook():
    cfg = json.loads(HOOKS.read_text(encoding="utf-8"))
    entries = cfg["hooks"]["PreToolUse"]
    ours = [e for e in entries if "guard_position.py" in json.dumps(e)]
    assert len(ours) == 1, "exactly one position-guard PreToolUse entry"
    entry = ours[0]
    assert set(entry["matcher"].split("|")) == set(gp.EDIT_TOOLS)
    cmds = [h["command"] for h in entry["hooks"] if h.get("type") == "command"]
    assert len(cmds) == 1
    assert "${CLAUDE_PLUGIN_ROOT}" in cmds[0], "resolve the script from the plugin root"
    assert cmds[0].startswith('sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" '), (
        "run the guard through the launcher; a bare python3 fails OPEN on a Store alias (LANES-17)")
    assert cmds[0].endswith(" guard_position.py || exit 2"), (
        "any failure to run the guard -- no sh, a crash -- must BLOCK, never allow")
    assert SCRIPT.exists()


def test_script_is_stdlib_only_apart_from_the_plugins_own_modules():
    """Runs under the system python3 the hook command names, never a venv."""
    import ast
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    assert mods <= {"__future__", "fnmatch", "json", "os", "subprocess", "sys", "dataclasses",
                    "pathlib", "typing", "_console", "lanes_config"}, mods
