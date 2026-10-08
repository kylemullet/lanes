"""Commit guard -- the position rule enforced by git itself, at ``pre-commit``.

The position guard (``guard_position.py``) is a ``PreToolUse`` hook on the edit tools,
so it never sees a file written through ``Bash`` (``sed -i``, a heredoc, a script) or a
commit made from a terminal. This is the other half: a git ``pre-commit`` hook that
judges the STAGED SET, whatever wrote it. Prose already said "work it in a worktree"
before the incident that made the rule, and was skipped at the moment it applied;
a commit that git itself refuses cannot be skipped by not reading (LANES-1).

The rule -- the same truth table as the edit-tool guard, over every staged path::

    allow   not the main clone AND not the main branch               (a lane)
    allow   main clone AND main branch AND every staged path is main-direct  (a claim, a close)
    refuse  main clone AND main branch AND any staged path is not main-direct
    refuse  main clone on any other branch, or detached               (the 2026-09-10 shape)
    refuse  a worktree with the main branch checked out

During a rebase, HEAD is detached; the branch being rebased (``rebase-merge/head-name``)
is the one judged, so resolving a conflict in a main-clone ``pull --rebase`` and running
``git commit`` is judged as a commit on the main branch, not refused as "detached".

``git commit --no-verify`` bypasses it, deliberately: this is a guardrail against the
automatic mistake, not a permission system. A guard with no way past it is a guard that
gets uninstalled the first time it is wrong.

Installing it -- no per-clone setup step
----------------------------------------
``--install`` writes a small ``pre-commit`` shim into the repository's hooks directory
(``git rev-parse --git-path hooks``, shared by every worktree). ``session-startup`` runs
it every session, so a fresh clone is guarded after its first startup and a plugin
update re-points the shim at the new version. It is idempotent and never overwrites a
``pre-commit`` hook it did not write; with ``core.hooksPath`` set it writes nothing (that
directory is usually tracked, and a hook framework owns it). Either case is reported,
and ``/lanes:doctor`` shows it as a warning with the line to add by hand.

The shim names the plugin's launcher by absolute path. If that path disappears (the
plugin was updated and the old cache removed before the next startup re-pointed it),
the shim ALLOWS the commit and says so on stderr: a stale path must not block every
commit in the repository, and the doctor reports it. When the launcher is there but no
working Python resolves, the launcher refuses (exit 2, LANES-17), and ``--no-verify``
is the way past.

``git.commit_guard = false`` in ``.claude/lanes/config.toml`` turns it off: the hook
allows everything, and ``--install`` removes the shim it wrote.

Usage::

    sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" guard_commit.py --install    # idempotent; one line
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" guard_commit.py --status     # installed / stale / absent / ...
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" guard_commit.py --explain    # judge the current staged set
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" guard_commit.py --hook       # what the shim runs
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import guard_position as gp            # noqa: E402
import lanes_config as lc              # noqa: E402

ALLOW, BLOCK = 0, 1
SHIM_MARKER = "# lanes commit guard (LANES-1)"
LAUNCHER = Path(__file__).resolve().parent / "lanes.sh"
SHOWN = 8   # staged paths named in a refusal before "and N more"


def _git(args, cwd) -> Optional[str]:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.rstrip("\n") if done.returncode == 0 else None


# ------------------------------------------------------------------ position
@dataclass(frozen=True)
class Where:
    toplevel: str
    main_clone: str
    branch: str          # the branch judged: HEAD's, or the one a rebase is rewriting; "HEAD" if detached
    git_dir: str


def _branch_being_rebased(git_dir: str) -> Optional[str]:
    for sub in ("rebase-merge", "rebase-apply"):
        head = Path(git_dir) / sub / "head-name"
        try:
            ref = head.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if ref.startswith("refs/heads/"):
            return ref[len("refs/heads/"):]
    return None


def where(cwd: str) -> Optional[Where]:
    toplevel = _git(["rev-parse", "--show-toplevel"], cwd)
    if not toplevel:
        return None
    common = _git(["rev-parse", "--git-common-dir"], toplevel)
    git_dir = _git(["rev-parse", "--absolute-git-dir"], toplevel)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], toplevel)
    if common is None or git_dir is None or branch is None:
        return None
    main_clone = os.path.dirname(os.path.realpath(os.path.join(toplevel, common)))
    if branch == "HEAD":
        branch = _branch_being_rebased(git_dir) or "HEAD"
    return Where(toplevel=os.path.abspath(toplevel), main_clone=main_clone, branch=branch, git_dir=git_dir)


def enabled(main_clone: str) -> bool:
    loaded = lc.load(root=Path(main_clone))
    git_t = loaded.raw.get("git") if loaded.found and isinstance(loaded.raw.get("git"), dict) else {}
    value = git_t.get("commit_guard", lc.DEFAULTS["git"]["commit_guard"])
    return value is not False


def staged_paths(toplevel: str) -> list:
    """Every path the commit touches; a rename counts as both its old and new path."""
    out = _git(["diff", "--cached", "--name-only", "--no-renames", "-z"], toplevel)
    return [p for p in (out or "").split("\0") if p]


# ------------------------------------------------------------------ the rule
def decide(staged: list, w: Where, rules: gp.Rules) -> tuple[int, str]:
    mb = rules.main_branch
    in_main_clone = os.path.realpath(w.toplevel) == os.path.realpath(w.main_clone)
    on_main = w.branch == mb
    bypass = "If you are certain, `git commit --no-verify` bypasses this guard once."

    if not in_main_clone and not on_main:
        return ALLOW, f"lane commit: {w.toplevel} on {w.branch}"

    if in_main_clone and on_main:
        bad = [p for p in staged if not gp.is_main_direct(p, rules.main_direct)]
        if not bad:
            return ALLOW, f"main-direct commit on {mb} in the main clone ({len(staged)} path(s))"
        named = ", ".join(bad[:SHOWN]) + (f" and {len(bad) - SHOWN} more" if len(bad) > SHOWN else "")
        return BLOCK, (
            f"lanes commit guard: refusing a commit on `{mb}` in the main clone that stages "
            f"{len(bad)} path(s) outside git.main_direct_paths: {named}.\n"
            f"Code never lands on `{mb}` from a commit made there. Unstage them "
            f"(`git restore --staged <path>`) and work them in a worktree:\n"
            f"    git worktree add ../<repo>-<topic> -b <topic>-work\n"
            f"Main-direct paths: {', '.join(rules.main_direct)}. {bypass}"
        )

    if in_main_clone:
        state = "a detached HEAD" if w.branch == "HEAD" else f"`{w.branch}`"
        return BLOCK, (
            f"lanes commit guard: the MAIN CLONE ({w.toplevel}) has {state} checked out, not "
            f"`{mb}`. A commit here goes into that branch; the incident behind this rule was a "
            f"docs commit swallowed by another lane's branch this way, dropped by its rebase. "
            f"`git checkout {mb}` for a claim, or commit from that lane's own worktree. {bypass}"
        )

    return BLOCK, (
        f"lanes commit guard: {w.toplevel} is a worktree with `{mb}` checked out. A lane "
        f"commits on a topic branch (`git switch -c <topic>-work`); a commit here is a commit "
        f"on `{mb}` outside the main clone, which no landing path expects. {bypass}"
    )


def evaluate(cwd: str) -> tuple[int, str]:
    w = where(cwd)
    if w is None:
        return ALLOW, "lanes commit guard: cannot read the repository's position; not checking"
    if not enabled(w.main_clone):
        return ALLOW, "lanes commit guard: off (git.commit_guard = false)"
    return decide(staged_paths(w.toplevel), w, gp.rules_for(w.main_clone, env={}))


# ------------------------------------------------------------------ the shim
def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def shim_text(launcher: Path = LAUNCHER) -> str:
    path = launcher.as_posix()
    return (
        "#!/bin/sh\n"
        f"{SHIM_MARKER}: refuses a commit that puts non-main-direct work on the main\n"
        "# branch, or any commit made in the main clone off it. Written by\n"
        "# `guard_commit.py --install`, which session-startup runs every session, so a plugin\n"
        "# update re-points it. Do not edit; bypass once with `git commit --no-verify`.\n"
        f"launcher={_sh_quote(path)}\n"
        'if [ ! -f "$launcher" ]; then\n'
        '    echo "lanes commit guard: $launcher is gone (plugin updated or removed); not checking'
        ' this commit -- run /lanes:doctor" >&2\n'
        "    exit 0\n"
        "fi\n"
        'exec sh "$launcher" guard_commit.py --hook\n'
    )


def hook_file(main_clone: str) -> tuple[Optional[Path], Optional[str]]:
    """(the pre-commit path, None) -- or (None, why it is not ours to write)."""
    hooks_path = _git(["config", "--get", "core.hooksPath"], main_clone)
    if hooks_path:
        return None, (f"core.hooksPath is set ({hooks_path}); lanes writes no hook there -- add "
                      f"`sh {LAUNCHER.as_posix()} guard_commit.py --hook` to that pre-commit by hand")
    rel = _git(["rev-parse", "--git-path", "hooks/pre-commit"], main_clone)
    if not rel:
        return None, "cannot resolve the hooks directory"
    p = Path(rel)
    return (p if p.is_absolute() else Path(main_clone) / p), None


def status(main_clone: str, launcher: Path = LAUNCHER) -> tuple[str, str]:
    """(state, detail). States: installed, stale, absent, foreign, hookspath, disabled, error."""
    hook, why = hook_file(main_clone)
    on = enabled(main_clone)
    if hook is None:
        state = "hookspath" if why and why.startswith("core.hooksPath") else "error"
        return ("disabled", "off (git.commit_guard = false)") if not on else (state, why or "")
    if not hook.exists():
        return ("disabled", "off (git.commit_guard = false)") if not on else ("absent", f"no pre-commit hook at {hook}")
    text = hook.read_text(encoding="utf-8", errors="replace")
    if SHIM_MARKER not in text:
        return "foreign", (f"{hook} is another tool's pre-commit hook; lanes leaves it alone -- add "
                           f"`sh {launcher.as_posix()} guard_commit.py --hook` to it by hand")
    if not on:
        return "stale", f"git.commit_guard = false but the shim is still at {hook}"
    if text == shim_text(launcher):
        return "installed", f"pre-commit shim at {hook}"
    return "stale", f"the shim at {hook} points at another plugin path"


def install(main_clone: str, launcher: Path = LAUNCHER) -> tuple[int, str]:
    """Idempotent. 0 = guarded (or deliberately off), 1 = could not install; the line says why."""
    hook, why = hook_file(main_clone)
    if hook is None:
        return (0, "commit guard: off (git.commit_guard = false)") if not enabled(main_clone) else (1, f"commit guard: not installed -- {why}")
    ours = hook.exists() and SHIM_MARKER in hook.read_text(encoding="utf-8", errors="replace")
    if not enabled(main_clone):
        if ours:
            hook.unlink()
            return 0, f"commit guard: off (git.commit_guard = false) -- removed {hook}"
        return 0, "commit guard: off (git.commit_guard = false)"
    if hook.exists() and not ours:
        return 1, (f"commit guard: not installed -- {hook} is another tool's pre-commit hook; add "
                   f"`sh {launcher.as_posix()} guard_commit.py --hook` to it by hand")
    want = shim_text(launcher)
    if ours and hook.read_text(encoding="utf-8", errors="replace") == want:
        return 0, "commit guard: installed (unchanged)"
    hook.parent.mkdir(parents=True, exist_ok=True)
    with open(hook, "w", encoding="utf-8", newline="\n") as fh:   # LF: git's sh reads it on every platform
        fh.write(want)
    os.chmod(hook, 0o755)
    return 0, f"commit guard: {'re-pointed' if ours else 'installed'} at {hook}"


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    use_utf8_console()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--hook", action="store_true", help="judge the staged set (what the shim runs)")
    mode.add_argument("--explain", action="store_true", help="judge the staged set and print the verdict")
    mode.add_argument("--install", action="store_true", help="write or re-point the pre-commit shim")
    mode.add_argument("--status", action="store_true", help="report the shim's state")
    ap.add_argument("--root", help="repository (default: the one containing the cwd)")
    args = ap.parse_args(argv)
    cwd = args.root or os.getcwd()

    if args.hook or args.explain:
        code, why = evaluate(cwd)
        if args.explain:
            print(f"{'ALLOW' if code == ALLOW else 'BLOCK'}: {why}")
        elif code != ALLOW:
            print(why, file=sys.stderr)
        return code

    w = where(cwd)
    if w is None:
        print("commit guard: not inside a git repository", file=sys.stderr)
        return 1
    if args.install:
        code, line = install(w.main_clone)
        print(line)
        return code
    state, detail = status(w.main_clone)
    print(f"{state}: {detail}")
    return 0 if state in ("installed", "disabled") else 1


if __name__ == "__main__":
    sys.exit(main())
