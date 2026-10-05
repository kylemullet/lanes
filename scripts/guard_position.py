"""Position guard for the edit tools -- the lanes plugin's ``PreToolUse`` hook.

`worktree-increment` step 0 says: before any write that is not the step-1 claim,
``git rev-parse --show-toplevel`` must NOT be the main clone and ``git rev-parse
--abbrev-ref HEAD`` must NOT be the main branch. Wired by ``hooks/hooks.json`` on
``Write|Edit|MultiEdit|NotebookEdit``, this script reads the tool call from stdin,
works out where the target file would land, and exits 2 (block) or 0 (allow).

The rule, and why it is EITHER rather than BOTH
-----------------------------------------------
A lane edit needs both conditions to hold, so the guard refuses when EITHER fails::

    refuse  if  toplevel == main_clone  OR  branch == main_branch
    allow   if  toplevel == main_clone  AND branch == main_branch  AND  path is main-direct
    allow   if  toplevel != main_clone  AND branch != main_branch               (a lane)

The incident that motivated the hook (2026-09-10) was a docs commit made in the main
clone while ANOTHER LANE'S BRANCH was checked out there: HEAD was not the main
branch, so an AND form would have passed the exact write that started it. The
carve-out is the claim commit's shape -- a main-direct path AND the main branch AND
the main clone. "Docs-only" alone is not enough: that write was itself docs-only.

Which repository the guard is FOR
---------------------------------
The one the session was started in: ``$CLAUDE_PROJECT_DIR``. A session loads hooks
from its starting directory, so this hook fires on every edit-tool write the
session makes anywhere -- including into some OTHER repository that happens to
have its main branch checked out. That repository's main branch is not a landing
path of this one, and no lane here can be damaged by a write there, so a target
whose main clone differs from ``$CLAUDE_PROJECT_DIR``'s is allowed as "foreign".
(Found the day the plugin was being built from a session in the project it was
extracted from: every write into the plugin's repo was refused.) With
``$CLAUDE_PROJECT_DIR`` unset the guard judges every repository it can see.

Where the rules come from
-------------------------
``.claude/lanes/config.toml`` in the TARGET's main clone: ``git.main_branch`` and
``git.main_direct_paths`` (each entry a directory prefix ending in ``/``, a
root-level glob containing ``*``, or an exact path). Missing config = the solo
defaults (``main``; ``docs/``, ``*.md``). This is the claim-push guard's list --
"may it reach the main branch with no branch and no suite run" -- which a project
may deliberately keep different from ``backlog.docs_lane_prefixes``.

Where position is measured
--------------------------
From the TARGET FILE's own directory, not the session's cwd. ``main_clone`` is
derived from ``git rev-parse --git-common-dir`` -- ``<main clone>/.git`` from any
worktree -- so nothing has to be configured.

What is allowed without looking
-------------------------------
* A tool that is not one of the four edit tools.
* A target outside any git repository, or in a foreign repository (above).
* A path git ignores: an ignored file can never end up in another lane's commit.
* Anything when ``git`` is missing or the stdin is not the hook's JSON. A guard
  that fails closed blocks every write everywhere, including the ones that would
  fix it. Fail open, say so on stderr, and let the skill carry the rule.

What it does NOT catch -- say this plainly
------------------------------------------
A ``PreToolUse`` hook on the edit tools never sees a file written through ``Bash``
(``sed -i``, a heredoc, a script). This converts the rule from "a model can skip
it" to "a model cannot skip it via the edit tools" -- most of the value -- but
never claim "cannot skip".

Testing
-------
``tests/test_guard_position.py`` drives every cell of the truth table through a
FAKE environment -- ``LANES_GUARD_TOPLEVEL`` / ``_MAIN_CLONE`` / ``_BRANCH`` /
``_IGNORED`` / ``_PROJECT_MAIN_CLONE`` / ``_MAIN_BRANCH`` / ``_MAIN_DIRECT`` -- so
no test depends on real git state; integration tests build throwaway repos and
run the real git path.

Usage::

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guard_position.py"    < hook JSON on stdin
    python3 scripts/guard_position.py --explain <path>             # dry run from a shell
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import lanes_config as lc              # noqa: E402

DEFAULT_MAIN_BRANCH = lc.DEFAULTS["git"]["main_branch"]
DEFAULT_MAIN_DIRECT = tuple(lc.DEFAULTS["git"]["main_direct_paths"])

EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
PATH_KEYS = ("file_path", "notebook_path")

ALLOW, BLOCK = 0, 2

ENV_TOPLEVEL = "LANES_GUARD_TOPLEVEL"
ENV_MAIN_CLONE = "LANES_GUARD_MAIN_CLONE"
ENV_BRANCH = "LANES_GUARD_BRANCH"
ENV_IGNORED = "LANES_GUARD_IGNORED"
ENV_PROJECT_MAIN_CLONE = "LANES_GUARD_PROJECT_MAIN_CLONE"   # fake for $CLAUDE_PROJECT_DIR's main clone
ENV_MAIN_BRANCH = "LANES_GUARD_MAIN_BRANCH"                 # fake config: git.main_branch
ENV_MAIN_DIRECT = "LANES_GUARD_MAIN_DIRECT"                 # fake config: git.main_direct_paths (os.pathsep)
ENV_PROJECT_DIR = "CLAUDE_PROJECT_DIR"

def _process_env() -> dict:
    """The eight variables this guard reads, each by its literal name, and nothing
    else -- never the whole environment and never a name chosen at run time. Seven
    are the fake-environment test seams; the eighth is CLAUDE_PROJECT_DIR. A
    credential in the installer's environment is not read."""
    found = {
        "LANES_GUARD_TOPLEVEL": os.getenv("LANES_GUARD_TOPLEVEL"),
        "LANES_GUARD_MAIN_CLONE": os.getenv("LANES_GUARD_MAIN_CLONE"),
        "LANES_GUARD_BRANCH": os.getenv("LANES_GUARD_BRANCH"),
        "LANES_GUARD_IGNORED": os.getenv("LANES_GUARD_IGNORED"),
        "LANES_GUARD_PROJECT_MAIN_CLONE": os.getenv("LANES_GUARD_PROJECT_MAIN_CLONE"),
        "LANES_GUARD_MAIN_BRANCH": os.getenv("LANES_GUARD_MAIN_BRANCH"),
        "LANES_GUARD_MAIN_DIRECT": os.getenv("LANES_GUARD_MAIN_DIRECT"),
        "CLAUDE_PROJECT_DIR": os.getenv("CLAUDE_PROJECT_DIR"),
    }
    return {k: v for k, v in found.items() if v is not None}


@dataclass(frozen=True)
class Rules:
    main_branch: str
    main_direct: tuple


@dataclass(frozen=True)
class Position:
    toplevel: str      # the checkout the target lands in (abspath, symlinks NOT resolved)
    main_clone: str    # the checkout that owns .git (realpath)
    branch: str        # `git rev-parse --abbrev-ref HEAD` -- "HEAD" when detached
    rules: Rules = Rules(DEFAULT_MAIN_BRANCH, DEFAULT_MAIN_DIRECT)

    @property
    def in_main_clone(self) -> bool:
        return os.path.realpath(self.toplevel) == os.path.realpath(self.main_clone)

    @property
    def on_main_branch(self) -> bool:
        return self.branch == self.rules.main_branch


def rules_for(main_clone: str, env=None) -> Rules:
    """`git.main_branch` + `git.main_direct_paths` from the TARGET repo's config, or the defaults."""
    env = _process_env() if env is None else env
    if env.get(ENV_TOPLEVEL):   # fake environment: rules come from the fake too
        direct = tuple(p for p in env.get(ENV_MAIN_DIRECT, "").split(os.pathsep) if p) or DEFAULT_MAIN_DIRECT
        return Rules(env.get(ENV_MAIN_BRANCH) or DEFAULT_MAIN_BRANCH, direct)
    loaded = lc.load(root=Path(main_clone))
    if not loaded.found or loaded.parse_error:
        return Rules(DEFAULT_MAIN_BRANCH, DEFAULT_MAIN_DIRECT)
    git_t = loaded.raw.get("git") if isinstance(loaded.raw.get("git"), dict) else {}
    branch = git_t.get("main_branch") if isinstance(git_t.get("main_branch"), str) else DEFAULT_MAIN_BRANCH
    direct = git_t.get("main_direct_paths")
    direct = tuple(direct) if isinstance(direct, list) and all(isinstance(x, str) for x in direct) else DEFAULT_MAIN_DIRECT
    return Rules(branch or DEFAULT_MAIN_BRANCH, direct)


def is_main_direct(rel: str, main_direct=DEFAULT_MAIN_DIRECT) -> bool:
    """Repo-relative, forward-slash path -> may it reach the main branch without a branch?

    Each entry: a directory prefix ending in `/`, a root-level glob containing `*`
    (top-level files only), or an exact repo-relative path.
    """
    rel = rel.replace(os.sep, "/")
    if rel.startswith("./"):
        rel = rel[2:]
    for entry in main_direct:
        e = str(entry).replace("\\", "/")
        if e.startswith("./"):
            e = e[2:]
        if e.endswith("/"):
            if rel.startswith(e):
                return True
        elif "*" in e:
            if "/" not in rel and fnmatch.fnmatch(rel, e):
                return True
        elif rel == e:
            return True
    return False


def target_path(tool_input: dict) -> Optional[str]:
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _git(args, cwd) -> Optional[str]:
    try:
        done = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def _nearest_existing_dir(path: str) -> str:
    here = os.path.dirname(os.path.abspath(path))
    while here and not os.path.isdir(here):
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return here


def position_of(path: str, env=None) -> Optional[Position]:
    """Where would a write to `path` land? None when no repo is visible from it."""
    env = _process_env() if env is None else env
    if env.get(ENV_TOPLEVEL):
        main_clone = os.path.abspath(env.get(ENV_MAIN_CLONE) or env[ENV_TOPLEVEL])
        rules = rules_for(main_clone, env)
        return Position(
            toplevel=os.path.abspath(env[ENV_TOPLEVEL]),
            main_clone=main_clone,
            branch=env.get(ENV_BRANCH, rules.main_branch),
            rules=rules,
        )
    start = _nearest_existing_dir(path)
    toplevel = _git(["rev-parse", "--show-toplevel"], start)
    if not toplevel:
        return None
    common = _git(["rev-parse", "--git-common-dir"], toplevel)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], toplevel)
    if common is None or branch is None:
        return None
    # `.git` (relative, main clone) or `/abs/main/.git` (a worktree); either way
    # its parent is the checkout that owns the repository.
    main_clone = os.path.dirname(os.path.realpath(os.path.join(toplevel, common)))
    return Position(toplevel=os.path.abspath(toplevel), main_clone=main_clone, branch=branch,
                    rules=rules_for(main_clone, env))


def project_main_clone(env=None) -> Optional[str]:
    """Realpath of the main clone of the repo the SESSION started in, or None if unknown."""
    env = _process_env() if env is None else env
    if env.get(ENV_TOPLEVEL):
        fake = env.get(ENV_PROJECT_MAIN_CLONE)
        return os.path.realpath(fake) if fake else None
    project_dir = env.get(ENV_PROJECT_DIR)
    if not project_dir or not os.path.isdir(project_dir):
        return None
    toplevel = _git(["rev-parse", "--show-toplevel"], project_dir)
    if not toplevel:
        return None
    common = _git(["rev-parse", "--git-common-dir"], toplevel)
    if common is None:
        return None
    return os.path.dirname(os.path.realpath(os.path.join(toplevel, common)))


def is_foreign(pos: Position, env=None) -> bool:
    """Is the target in a repository other than the one the session was started in?"""
    project = project_main_clone(env)
    return project is not None and os.path.realpath(pos.main_clone) != project


def relative_to_toplevel(path: str, toplevel: str) -> Optional[str]:
    """Repo-relative forward-slash path, or None when `path` is outside `toplevel`."""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(toplevel))
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return rel.replace(os.sep, "/")


def is_ignored(rel: str, toplevel: str, env=None) -> bool:
    env = _process_env() if env is None else env
    if env.get(ENV_TOPLEVEL):
        listed = [p.replace(os.sep, "/") for p in env.get(ENV_IGNORED, "").split(os.pathsep) if p]
        return rel in listed
    try:
        done = subprocess.run(
            ["git", "check-ignore", "-q", "--", rel], cwd=toplevel,
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def decide(rel: str, pos: Position) -> tuple[int, str]:
    """The truth table. Returns (exit code, one-paragraph reason)."""
    mb = pos.rules.main_branch
    if not pos.in_main_clone and not pos.on_main_branch:
        return ALLOW, f"lane write: {pos.toplevel} on {pos.branch}"

    if pos.in_main_clone and pos.on_main_branch:
        if is_main_direct(rel, pos.rules.main_direct):
            return ALLOW, f"main-direct write on {mb} in the main clone: {rel}"
        return BLOCK, (
            f"Blocked by the lanes position guard: `{rel}` is not a main-direct path, and this "
            f"write would land in the MAIN CLONE on `{mb}`. Code never lands on `{mb}` from a "
            f"commit made there (branch policy). Work it in a worktree on a topic branch -- "
            f"`worktree-increment` step 0 -- and keep only the claim, the closing docs and the "
            f"startup/closeout writes here. Main-direct paths (git.main_direct_paths): "
            f"{', '.join(pos.rules.main_direct)}."
        )

    if pos.in_main_clone:  # and NOT on the main branch
        return BLOCK, (
            f"Blocked by the lanes position guard: the MAIN CLONE ({pos.toplevel}) has "
            f"`{pos.branch}` checked out, not `{mb}`. A write here goes into that branch -- "
            f"the 2026-09-10 incident: a docs commit made in the main clone while another lane's "
            f"branch was checked out was swallowed by that branch, dropped by its rebase, and left "
            f"`{mb}` advertising a false claim for a day. Even a docs-only write is refused in "
            f"this state. Either `git checkout {mb}` in the main clone for a claim, or make the "
            f"edit in that lane's own worktree."
        )

    # Not the main clone, but on the main branch: a worktree checked out at the main branch.
    return BLOCK, (
        f"Blocked by the lanes position guard: {pos.toplevel} is a worktree with `{mb}` checked "
        f"out. A lane works on a topic branch; a write here is a commit on `{mb}` outside the "
        f"main clone, which no landing path expects. Create a branch (`git switch -c "
        f"<topic>-work`) or work in the main clone for a claim."
    )


def evaluate(payload: dict, env=None) -> tuple[int, str]:
    """Pure entry point over the parsed hook JSON: (exit code, reason)."""
    env = _process_env() if env is None else env
    tool = payload.get("tool_name")
    if tool not in EDIT_TOOLS:
        return ALLOW, f"not an edit tool: {tool!r}"
    tool_input = payload.get("tool_input") or {}
    path = target_path(tool_input) if isinstance(tool_input, dict) else None
    if not path:
        return ALLOW, "no target path in tool_input"
    pos = position_of(path, env)
    if pos is None:
        return ALLOW, "no git repository visible from the target; not this guard's business"
    if is_foreign(pos, env):
        return ALLOW, f"foreign repository ({pos.main_clone}); not this guard's business"
    rel = relative_to_toplevel(path, pos.toplevel)
    if rel is None:
        return ALLOW, f"target is outside {pos.toplevel}"
    if is_ignored(rel, pos.toplevel, env):
        return ALLOW, f"git ignores {rel}; it can never reach a commit"
    return decide(rel, pos)


def main(argv=None) -> int:
    use_utf8_console()
    argv = sys.argv[1:] if argv is None else argv

    if argv[:1] == ["--explain"]:
        if len(argv) != 2:
            print("usage: guard_position.py --explain <path>", file=sys.stderr)
            return 1
        code, why = evaluate({"tool_name": "Edit", "tool_input": {"file_path": argv[1]}})
        print(f"{'ALLOW' if code == ALLOW else 'BLOCK'}: {why}")
        return code

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        print(f"guard_position: stdin was not hook JSON ({exc}); allowing", file=sys.stderr)
        return ALLOW
    if not isinstance(payload, dict):
        print("guard_position: hook JSON was not an object; allowing", file=sys.stderr)
        return ALLOW

    code, why = evaluate(payload)
    if code == BLOCK:
        print(why, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
