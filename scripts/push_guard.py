"""May what is ahead of `origin/<main>` reach it with no operator OK? One guard, two modes.

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage (in the MAIN clone, on the main branch):
  python3 push_guard.py --ok-free           # check only: exit 0 = may push without an OK
  python3 push_guard.py --ok-free --push    # the same, then push (rebase-and-retry on a rejection)
  python3 push_guard.py --claim             # the claim push's rule (git.main_direct_paths)
  python3 push_guard.py --ok-free --push --add docs/backlog/UI/UI-9-x.md -m "docs(backlog): …"
                                            # commit those paths (only those) first, then guard + push

The plugin had two OK-free pushes to the main branch, each with its own copy of the
rule: the claim (`lanes_claim.py`, every path main-direct) and the backfill close
(`backlog_index.py --backfill --push`, every path under the backlog dir). Every other
backlog write -- a staleness fix, a released claim, an issue minted mid-session --
waited for "the next push", which is only as soon as the next OK. LANES-5 names the
rule once and lets every backlog write use it.

  --ok-free  every path in `origin/<main>..HEAD` is under `git.ok_free_paths` (default:
             the backlog dir alone -- NOT main_direct_paths: the standing docs change
             rules every session reads as ground truth, so they keep the OK), AND
             `backlog_index.py --check` is green, AND no commit ahead edits a claim
             marker another machine wrote. An OK-free push publishes at once, which
             makes a write to someone else's claim more dangerous, not less.
  --claim    every path is under `git.main_direct_paths` (the claim's rule, unchanged).

What "another machine's claim" can and cannot see: a marker names its author as
`<Short>'s session on <machine id>@<host>`. A changed or removed marker naming a
different machine id is refused. Two sessions on ONE machine share an id, so the guard
cannot tell them apart -- that rule stays a prohibition in the skills. A marker that
predates the machine field (`Kyle's session`) is compared by the person's short.

Exit status: 0 the guard passed (and, with --push, HEAD is on origin); 1 refused,
nothing pushed (the reasons are printed); 2 the guard passed but the push failed.
"""
import argparse, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import lanes_config as lc              # noqa: E402
from guard_position import is_main_direct  # noqa: E402

OK_FREE, CLAIM = "ok-free", "claim"
REFUSED, NOT_PUSHED = 1, 2

# `⏳ IN-PROGRESS (2026-10-07 04:00, Kyle's session on kyle-mac@host, worktree …) — **KIND.**`
_MARKER_AUTHOR = re.compile(
    r"⏳ IN-PROGRESS \(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?, (?P<who>[^,)]+)")
_SESSION = re.compile(r"^(?P<short>.+?)'s session(?: on (?P<machine>[^@\s]+)@\S+)?")


def git(*args, cwd):
    """(returncode, stdout, stderr); never raises."""
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def ancestor(a, b, cwd):
    return git("merge-base", "--is-ancestor", a, b, cwd=cwd)[0] == 0


def allowed_paths(cfg, mode):
    return cfg["ok_free_paths"] if mode == OK_FREE else cfg["main_direct_paths"]


def ahead_paths(root, main):
    """Every path touched by a commit in `origin/<main>..HEAD`, or None when git fails."""
    rc, out, _ = git("log", f"origin/{main}..HEAD", "--name-only", "--format=", cwd=root)
    return None if rc else sorted({p for p in out.splitlines() if p})


def stray_paths(root, cfg, mode):
    """Paths ahead of origin that the mode does not let through without an OK."""
    paths = ahead_paths(root, cfg["main_branch"])
    if paths is None:
        return ["(git log failed)"]
    allowed = allowed_paths(cfg, mode)
    return [p for p in paths if not is_main_direct(p, allowed)]


def marker_author(line):
    """(short, machine id or None) of a ⏳ marker line, or None when it is not one."""
    m = _MARKER_AUTHOR.search(line)
    if not m:
        return None
    s = _SESSION.match(m.group("who").strip())
    if not s:
        return (m.group("who").strip().lower(), None)
    return (s.group("short").strip().lower(), s.group("machine"))


def is_mine(author, machine):
    """Did THIS machine write a marker by `author`? Machine id when the marker has one."""
    short, mid = author
    if mid:
        return mid == machine["id"]
    return short == (machine["short"] or "").lower()


def foreign_claim_edits(root, cfg):
    """`<path>: <marker author>` for every marker line a commit ahead REMOVES (or rewrites)
    that this machine did not write. Adding a marker is a claim, and the claim script has
    its own refusals; this guard only watches edits to markers that already existed."""
    main, backlog = cfg["main_branch"], cfg["backlog_dir"].strip("/")
    rc, diff, _ = git("diff", "--no-color", "--unified=0", f"origin/{main}...HEAD", "--",
                      backlog + "/", cwd=root)
    if rc:
        return []
    out, path = [], None
    for line in diff.splitlines():
        if line.startswith("--- "):
            path = line[6:] if line.startswith("--- a/") else None
        elif line.startswith("-") and not line.startswith("---") and path:
            author = marker_author(line[1:])
            if author and not is_mine(author, cfg["machine"]):
                who = author[1] or author[0]
                out.append(f"{path}: a claim marker by `{who}`")
    return out


def backlog_check(root):
    script = Path(__file__).resolve().parent / "backlog_index.py"
    proc = subprocess.run([sys.executable, str(script), "--root", str(root), "--check"],
                          cwd=root, capture_output=True, text=True, encoding="utf-8")
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def problems(root, cfg, mode, run_check=True):
    """Every reason the commits ahead may NOT reach the main branch without an OK."""
    out = []
    stray = stray_paths(root, cfg, mode)
    if stray:
        names = ", ".join(stray[:3]) + (f" +{len(stray) - 3} more" if len(stray) > 3 else "")
        kind = "git.ok_free_paths" if mode == OK_FREE else "git.main_direct_paths"
        out.append(f"commits ahead of origin/{cfg['main_branch']} touch paths outside {kind}: {names}")
    if mode == OK_FREE:
        out += [f"edits another machine's claim — {e}" for e in foreign_claim_edits(root, cfg)]
        if run_check and not stray:
            ok, msg = backlog_check(root)
            if not ok:
                out.append("backlog --check is red:\n" + msg)
    return out


def push(root, cfg, mode, attempts=3, run_check=True):
    """Guard, then push HEAD to origin/<main>, converging on a rejection by fetch + rebase
    (never a force). The guard re-runs after every rebase: what came in may change it.
    Returns (code, message) with code 0 pushed / 1 refused / 2 not pushed."""
    main = cfg["main_branch"]
    upstream = f"origin/{main}"
    for _ in range(attempts):
        found = problems(root, cfg, mode, run_check=run_check)
        if found:
            return REFUSED, "; ".join(found)
        if ancestor("HEAD", upstream, root):
            return 0, f"nothing to push — {upstream} already has HEAD"
        rc, _, err = git("push", "-q", "origin", f"HEAD:{main}", cwd=root)
        if rc == 0:
            return 0, f"pushed to {upstream}"
        rc, _, ferr = git("fetch", "-q", "origin", main, cwd=root)
        if rc:
            return NOT_PUSHED, f"push rejected and the re-fetch failed: {ferr or err}"
        rc, _, rerr = git("rebase", "-q", "--autostash", upstream, cwd=root)
        if rc:
            git("rebase", "--abort", cwd=root)
            first = rerr.splitlines()[0] if rerr else "conflict"
            return NOT_PUSHED, (f"push rejected; rebasing onto {upstream} conflicted ({first}) — "
                                "rebase aborted, the commits are local")
    return NOT_PUSHED, f"push rejected {attempts} times — the commits are local; pull and re-run"


def commit_paths(root, paths, subject):
    """Stage exactly `paths` and commit them alone. Returns an error string or None."""
    rc, _, err = git("add", "--", *paths, cwd=root)
    if not rc:
        rc, _, err = git("commit", "-q", "-m", subject, "--", *paths, cwd=root)
    return (err or "git commit failed") if rc else None


def position(root, main):
    """None when root is the main clone on the main branch, else why not."""
    _, git_dir, _ = git("rev-parse", "--absolute-git-dir", cwd=root)
    _, common, _ = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=root)
    if git_dir and common and Path(git_dir).resolve() != Path(common).resolve():
        return "this is a lane worktree — an OK-free push is made from the main clone"
    _, branch, _ = git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    if branch != main:
        return f"the main clone is on `{branch}`, not `{main}`"
    return None


def load_cfg(root):
    loaded = lc.load(root=root)
    if loaded.parse_error:
        raise SystemExit(f"lanes config does not parse: {loaded.parse_error}")
    return lc.resolve(loaded.raw, user_name=lc.git_user_name(root))


def main(argv=None):
    use_utf8_console()
    ap = argparse.ArgumentParser(description="lanes: may the commits ahead of origin reach the main branch without an OK?")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ok-free", dest="mode", action="store_const", const=OK_FREE,
                      help="git.ok_free_paths + backlog --check + no edit to another machine's claim")
    mode.add_argument("--claim", dest="mode", action="store_const", const=CLAIM,
                      help="git.main_direct_paths (the claim push's rule)")
    ap.add_argument("--push", action="store_true", help="push when the guard passes")
    ap.add_argument("--add", nargs="+", metavar="PATH", default=None,
                    help="commit exactly these paths first (with -m); never a broad add")
    ap.add_argument("-m", "--message", default=None, help="the subject for --add's commit")
    ap.add_argument("--root", default=None, help="repository (default: the one containing the cwd)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else (lc.repo_root() or Path.cwd())
    cfg = load_cfg(root)
    where = position(root, cfg["main_branch"])
    if where:
        print(f"NOT PUSHED — {where}.", file=sys.stderr)
        return REFUSED
    if args.add:
        if not args.message:
            ap.error("--add needs -m <subject>")
        err = commit_paths(root, args.add, args.message)
        if err:
            print(f"NOT COMMITTED — {err}", file=sys.stderr)
            return REFUSED
        print(f"committed: {args.message}")
    if args.push:
        code, msg = push(root, cfg, args.mode)
        print(("OK — " if code == 0 else "NOT PUSHED — ") + msg, file=sys.stdout if code == 0 else sys.stderr)
        return code
    if git("fetch", "-q", "origin", cfg["main_branch"], cwd=root)[0]:
        print("warning: fetch failed; judging against the last-fetched origin", file=sys.stderr)
    found = problems(root, cfg, args.mode)
    if found:
        for p in found:
            print(f"REFUSED — {p}", file=sys.stderr)
        return REFUSED
    print(f"OK — everything ahead of origin/{cfg['main_branch']} may be pushed without an OK ({args.mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
