"""Backlog view hooks -- keep the bookmarked file:// view fresh after any pull (LANES-11).

The view is a file the operator bookmarks (``<main clone>/<backlog.dir>/index.html``),
not a server, so it is only as fresh as its last generation. Every lanes script that
writes the backlog regenerates it (``backlog_index.refresh_main_view``); this covers the
writes no lanes script makes: a ``git pull`` in a terminal, a rebase, a branch switch.
Three git hooks, all run in the main clone only:

    post-merge      a fast-forward or merge pull (``git pull --rebase`` that only
                    fast-forwards lands here too)
    post-rewrite    a rebase that replayed local commits (``rebase``), or an ``--amend``
    post-checkout   a branch switch; skipped while a rebase is in progress, which
                    post-rewrite covers, and for a file checkout

``git worktree add`` fires post-checkout INSIDE the new worktree; the hook ignores it,
since nothing in the main clone changed. The refresh writes only where both views are
gitignored, takes well under a second, prints nothing on success, and never fails the
git command that ran it.

Installing it -- no per-clone setup step
----------------------------------------
``--install`` writes a marked block into each hook (``git rev-parse --git-path hooks``,
shared by every worktree). ``session-startup`` runs it every session, beside the commit
guard, so a fresh clone gets it at its first startup and a plugin update re-points it.
Unlike the commit guard it CHAINS: a hook another tool wrote (git-lfs writes
post-checkout and post-merge) keeps its lines, and the block is appended after them.
It is not written when the existing hook is not a shell script, or hands off with
``exec`` (nothing after that line runs), or when ``core.hooksPath`` is set; each is
reported, and ``/lanes:doctor`` shows it with the line to add by hand.

``backlog.view_mode = "serve"`` turns it off: the served view re-parses per request,
so ``--install`` removes the blocks it wrote.

Usage::

    sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" view_hooks.py --install   # idempotent; one line
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" view_hooks.py --status
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" view_hooks.py --hook <hook name> [git's args]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import guard_commit as gc              # noqa: E402
import lanes_config as lc              # noqa: E402

HOOKS = ("post-merge", "post-rewrite", "post-checkout")
BEGIN = "# >>> lanes backlog view (LANES-11)"
END = "# <<< lanes backlog view"
LAUNCHER = Path(__file__).resolve().parent / "lanes.sh"
SHELLS = ("sh", "bash", "dash", "zsh", "ksh")


def enabled(main_clone: str) -> bool:
    """True unless the config says `backlog.view_mode = "serve"`."""
    loaded = lc.load(root=Path(main_clone))
    backlog = loaded.raw.get("backlog") if loaded.found and isinstance(loaded.raw.get("backlog"), dict) else {}
    return backlog.get("view_mode", lc.DEFAULTS["backlog"]["view_mode"]) != "serve"


def block(name: str, launcher: Path = LAUNCHER) -> str:
    return (
        f"{BEGIN}\n"
        "# Regenerates the main clone's backlog view. Written by `view_hooks.py --install`,\n"
        "# which session-startup runs every session. Do not edit; never fails the git command.\n"
        f"lanes_view={gc._sh_quote(launcher.as_posix())}\n"
        f'[ -f "$lanes_view" ] && sh "$lanes_view" view_hooks.py --hook {name} "$@" || true\n'
        f"{END}\n"
    )


def hook_file(main_clone: str, name: str) -> tuple[Optional[Path], Optional[str]]:
    """(the hook's path, None) -- or (None, why it is not ours to write)."""
    hooks_path = gc._git(["config", "--get", "core.hooksPath"], main_clone)
    if hooks_path:
        return None, (f"core.hooksPath is set ({hooks_path}); lanes writes no hook there -- add "
                      f"`sh {LAUNCHER.as_posix()} view_hooks.py --hook <name> \"$@\"` to its "
                      f"{', '.join(HOOKS)} by hand")
    rel = gc._git(["rev-parse", "--git-path", f"hooks/{name}"], main_clone)
    if not rel:
        return None, "cannot resolve the hooks directory"
    p = Path(rel)
    return (p if p.is_absolute() else Path(main_clone) / p), None


def _split(text: str) -> tuple[str, Optional[str]]:
    """(the hook without our block, our block or None)."""
    start = text.find(BEGIN)
    if start < 0:
        return text, None
    end = text.find(END, start)
    end = len(text) if end < 0 else end + len(END)
    if text[end:end + 1] == "\n":
        end += 1
    return text[:start] + text[end:], text[start:end]


def _unchainable(rest: str) -> Optional[str]:
    """Why a hook another tool wrote cannot take our block, or None."""
    lines = rest.splitlines()
    first = lines[0] if lines else ""
    parts = first[2:].split() if first.startswith("#!") else []
    if parts and os.path.basename(parts[0]) == "env":
        parts = parts[1:]
    if not parts or os.path.basename(parts[0]) not in SHELLS:
        return "is not a shell script"
    if any(l.lstrip().startswith("exec ") for l in lines):
        return "hands off with `exec`, so nothing appended after it would run"
    return None


def status_one(main_clone: str, name: str, launcher: Path = LAUNCHER) -> tuple[str, str]:
    """States: installed, stale, absent, foreign, hookspath, disabled, error."""
    hook, why = hook_file(main_clone, name)
    on = enabled(main_clone)
    if hook is None:
        if not on:
            return "disabled", "off (backlog.view_mode = serve)"
        return ("hookspath" if why and why.startswith("core.hooksPath") else "error"), why or ""
    text = hook.read_text(encoding="utf-8", errors="replace") if hook.exists() else ""
    rest, ours = _split(text)
    if not on:
        return ("stale", f"backlog.view_mode = serve but {hook} still carries the block") if ours \
            else ("disabled", "off (backlog.view_mode = serve)")
    if ours is None:
        if not hook.exists():
            return "absent", f"no {name} hook at {hook}"
        bad = _unchainable(rest)
        if bad:
            return "foreign", (f"{hook} {bad}; add `sh {launcher.as_posix()} view_hooks.py --hook {name} "
                               f"\"$@\"` to it by hand")
        return "absent", f"{hook} has no lanes block"
    if ours == block(name, launcher):
        return "installed", f"{hook}"
    return "stale", f"the block in {hook} points at another plugin path"


def status(main_clone: str, launcher: Path = LAUNCHER) -> tuple[str, str]:
    """The worst state over the three hooks, with every hook that is not installed named."""
    rank = ("installed", "disabled", "stale", "absent", "foreign", "hookspath", "error")
    states = {name: status_one(main_clone, name, launcher) for name in HOOKS}
    worst = max((s for s, _ in states.values()), key=rank.index)
    if worst in ("installed", "disabled"):
        detail = ("off (backlog.view_mode = serve)" if worst == "disabled"
                  else f"{', '.join(HOOKS)} refresh the view")
        return worst, detail
    return worst, "; ".join(f"{n}: {d}" for n, (s, d) in states.items() if s not in ("installed", "disabled"))


def install_one(main_clone: str, name: str, launcher: Path = LAUNCHER) -> tuple[str, Optional[str]]:
    """(outcome, problem). Outcomes: unchanged, installed, re-pointed, removed, off, refused."""
    hook, why = hook_file(main_clone, name)
    on = enabled(main_clone)
    if hook is None:
        return ("off", None) if not on else ("refused", why)
    text = hook.read_text(encoding="utf-8", errors="replace") if hook.exists() else ""
    rest, ours = _split(text)
    if not on:
        if ours is None:
            return "off", None
        if rest.strip() in ("", "#!/bin/sh"):
            hook.unlink()
        else:
            _write(hook, rest)
        return "removed", None
    want = block(name, launcher)
    if ours == want:
        return "unchanged", None
    if not text:
        _write(hook, "#!/bin/sh\n" + want)
        return "installed", None
    if ours is None:
        bad = _unchainable(rest)
        if bad:
            return "refused", f"{hook} {bad}"
    body = rest if rest.endswith("\n") else rest + "\n"
    _write(hook, body + want)
    return ("re-pointed" if ours else "installed"), None


def _write(hook: Path, text: str) -> None:
    hook.parent.mkdir(parents=True, exist_ok=True)
    with open(hook, "w", encoding="utf-8", newline="\n") as fh:   # LF: git's sh reads it on every platform
        fh.write(text)
    os.chmod(hook, 0o755)


def install(main_clone: str, launcher: Path = LAUNCHER) -> tuple[int, str]:
    """Idempotent. 0 = every hook carries the block (or deliberately off), 1 = one could not."""
    done = {name: install_one(main_clone, name, launcher) for name in HOOKS}
    problems = [f"{n}: {p}" for n, (o, p) in done.items() if o == "refused"]
    if problems:
        return 1, "view hooks: not installed -- " + "; ".join(problems)
    outcomes = {o for o, _ in done.values()}
    if outcomes <= {"off", "removed"}:
        return 0, ("view hooks: off (backlog.view_mode = serve)"
                   + (" -- removed the blocks" if "removed" in outcomes else ""))
    if outcomes == {"unchanged"}:
        return 0, "view hooks: installed (unchanged)"
    changed = [n for n, (o, _) in done.items() if o != "unchanged"]
    verb = "re-pointed" if outcomes - {"unchanged"} == {"re-pointed"} else "installed"
    return 0, f"view hooks: {verb} ({', '.join(changed)})"


# ------------------------------------------------------------------ the hook
def run_hook(cwd: str, name: str, args: list) -> int:
    """Refresh the main clone's view when this git event changed the main clone. Always 0."""
    w = gc.where(cwd)
    if w is None or os.path.realpath(w.toplevel) != os.path.realpath(w.main_clone):
        return 0                       # a worktree's checkout leaves the main clone's files alone
    if name == "post-checkout":
        if len(args) >= 3 and args[2] != "1":
            return 0                   # a file checkout, not a branch switch
        if any((Path(w.git_dir) / d).exists() for d in ("rebase-merge", "rebase-apply")):
            return 0                   # mid-rebase; post-rewrite refreshes once it is done
    if not enabled(w.main_clone):
        return 0
    try:
        import backlog_index as bidx
        bidx.configure(Path(w.main_clone))
        bidx.refresh_main_view()
    except Exception as e:             # noqa: BLE001 -- never fail the git command
        print(f"lanes: backlog view not refreshed ({e})", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    use_utf8_console()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true", help="write or re-point the hook blocks")
    mode.add_argument("--status", action="store_true", help="report the hooks' state")
    mode.add_argument("--hook", metavar="NAME", choices=HOOKS, help="what the hook block runs")
    ap.add_argument("--root", help="repository (default: the one containing the cwd)")
    args, rest = ap.parse_known_args(argv)
    cwd = args.root or os.getcwd()
    if args.hook:
        return run_hook(cwd, args.hook, rest)
    if rest:
        ap.error(f"unrecognized arguments: {' '.join(rest)}")
    w = gc.where(cwd)
    if w is None:
        print("view hooks: not inside a git repository", file=sys.stderr)
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
