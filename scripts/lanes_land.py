"""Land a lane's branch on the main branch, verify it landed, and only then clean up.

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage (from inside the lane's worktree, after the operator's landing OK):
  python3 lanes_land.py              # land, verify, remove the worktree, delete the branch
  python3 lanes_land.py --keep       # land and verify; leave the worktree and the branch
  python3 lanes_land.py --dry-run    # every check, no push, no clean-up
  python3 lanes_land.py --onto next  # land on another integration branch than git.main_branch
  python3 lanes_land.py --no-close   # land and clean up; leave the backfill to closeout/startup

`worktree-increment` step 9.7 and step 10 as one operation whose order cannot be
broken (LANES-20). The skill used to describe them as separate prose steps, and a
session ran them as one shell line joined by `;`: the fast-forward check failed
because another session had pushed seconds earlier, nothing landed, and the
clean-up ran anyway -- the worktree removed and the branch deleted locally AND on
origin. The commit survived only as an unreachable object.

The sequence, each step gating the next:

  1. Refuse, touching nothing, when this is the main clone or the main branch, the
     tree has uncommitted or untracked changes, or this machine's operator row does
     not certify.
  2. Fetch, and refuse unless `origin/<main>` is an ancestor of HEAD (a fast-forward).
     Losing that race is routine with concurrent sessions; the answer is rebase (a
     re-run only after a hand-resolved logic conflict, LANES-34), never force. Refuse, too, a landing that moves `plugin_version` to a
     version whose release tag is not on the plugin's remote (LANES-33): a consumer's CI
     checks the plugin out at that tag, and an untagged pin turned every push after it
     red. The plugin's CI mints the tag seconds after a release reaches `next`, so the
     check waits up to TAG_WAIT_SECONDS for it before refusing.
  3. Push `<branch>:<main>` -- exactly this branch's commits.
  4. Re-fetch and require HEAD to be an ancestor of `origin/<main>`: "landed" is a
     fact read back from the remote, not inferred from a push exit status.
  5. Only then, from the main clone: remove the worktree (never `--force`), delete the
     local branch, and delete the remote branch when its tip has landed too (another
     machine may have pushed to it since).

  6. Close the issue that just landed (LANES-21): run
     `backlog_index.py --backfill --push --isolated`. The resolving commit's hash became
     final at step 4, so `verified` has nothing left to wait for. `--isolated` closes from
     a throwaway worktree detached at a freshly fetched `origin/<main>` and pushes from
     there (LANES-23): the main clone is shared by every session on the machine, and the
     first real landing met another session's claim, committed there and not yet pushed,
     which made an in-place close refuse on the divergence. The main clone's branch,
     index and files are never touched, so it does not show the close until its next
     pull. The backfill also closes any other verified issue whose subject is on
     `origin/<main>`. Skipped when landing `--onto` another branch or when the repo has
     no backlog dir. The operator's landing OK covers it: it is the landed lane's own
     bookkeeping.

Exit status: 0 landed (and cleaned, unless --keep); 1 NOT landed -- nothing was
pushed, removed or deleted; 2 landed, but a clean-up step was skipped or failed (each
is named: the work is on the main branch, so what is left is litter, not loss), or the
close did not complete (the startup backfill is the backstop).

The operator's OK is the skill's gate, not this script's: run it after the OK.
"""
import argparse, subprocess, sys, time, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import lanes_config as lc              # noqa: E402
import release_tag as rt               # noqa: E402

NOT_LANDED, CLEANUP_INCOMPLETE = 1, 2
TAG_WAIT_SECONDS, TAG_POLL_SECONDS = 90, 10


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


class Refused(Exception):
    """A pre-landing check failed; nothing has been changed."""


def pinned_version(rev, cwd):
    """`plugin_version` in the config at `rev`, or None (no config, no pin, unparseable)."""
    rc, text, _ = git("show", f"{rev}:{lc.CONFIG_REL}", cwd=cwd)
    if rc:
        return None
    try:
        value = tomllib.loads(text).get("plugin_version")
    except tomllib.TOMLDecodeError:
        return None
    return value if isinstance(value, str) and value else None


def check_pin_is_released(upstream, cwd, wait=None):
    """Refuse a landing that pins an untagged plugin version (LANES-33). Returns a note
    to print, or None when the landing does not move the pin."""
    new = pinned_version("HEAD", cwd)
    if new is None or new == pinned_version(upstream, cwd):
        return None
    tag, remote = rt.tag_name(new), rt.release_remote()
    if remote is None:
        return f"pin {new}: release-tag lookup is off ({rt.REMOTE_ENV} is empty) — not checked"
    deadline = time.monotonic() + (TAG_WAIT_SECONDS if wait is None else wait)
    while True:
        found = rt.tag_on_remote(new, remote)
        if found:
            return f"pin {new}: {tag} is on {remote}"
        if time.monotonic() >= deadline:
            break
        time.sleep(TAG_POLL_SECONDS)
    if found is None:
        raise Refused(f"this landing pins plugin_version {new} and {remote} could not be asked for {tag} — "
                      f"retry once it answers, or set {rt.REMOTE_ENV}= (empty) to land without the check")
    raise Refused(f"this landing pins plugin_version {new}, but {tag} is not on {remote} — a consumer whose CI "
                  "checks out the pinned release goes red on every push until it exists. Release the version "
                  "first: from the plugin checkout, `python3 scripts/release_tag.py --ensure --push` (its CI's "
                  "release-tag job does the same on a push to next/main); then run this again")


def position(cwd):
    """(worktree root, main clone root, branch) -- or Refused."""
    rc, top, err = git("rev-parse", "--show-toplevel", cwd=cwd)
    if rc:
        raise Refused(f"not inside a git worktree: {err}")
    top = Path(top).resolve()
    _, git_dir, _ = git("rev-parse", "--absolute-git-dir", cwd=top)
    _, common, _ = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=top)
    if Path(git_dir).resolve() == Path(common).resolve():
        raise Refused(f"{top} is the main clone — run this from the lane's worktree")
    rc, branch, _ = git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=top)
    if rc:
        raise Refused("HEAD is detached — check out the lane's branch")
    return top, Path(common).resolve().parent, branch


def plan(cwd, onto=None):
    """Run every pre-landing check. Returns a dict for land(); raises Refused."""
    top, main_clone, branch = position(cwd)
    loaded = lc.load(top)
    if loaded.parse_error:
        raise Refused(f"lanes config does not parse: {loaded.parse_error}")
    cfg = lc.resolve(loaded.raw, user_name=lc.git_user_name(top))
    main = onto or cfg["main_branch"]
    if branch == main:
        raise Refused(f"on `{main}` — a lane lands from its topic branch")
    if not cfg["machine"].get("certifies"):
        raise Refused(f"this machine ({cfg['machine']['id']}) does not certify — push the branch "
                      "and leave the landing to a certifying machine")
    rc, dirty, err = git("status", "--porcelain", "--untracked-files=all", cwd=top)
    if rc or dirty:
        raise Refused("the worktree has uncommitted or untracked changes — commit or remove them first"
                      + (f" ({dirty.splitlines()[0]}" + (f" +{len(dirty.splitlines()) - 1} more)" if len(dirty.splitlines()) > 1 else ")")
                         if dirty else f": {err}"))
    rc, _, err = git("fetch", "-q", "origin", cwd=top)
    if rc:
        raise Refused(f"git fetch origin failed: {err}")
    upstream = f"origin/{main}"
    if git("rev-parse", "--verify", "--quiet", upstream, cwd=top)[0]:
        raise Refused(f"{upstream} does not exist")
    if not ancestor(upstream, "HEAD", top):
        raise Refused(f"{upstream} moved and is not an ancestor of HEAD — rebase onto it (a clean "
                      "rebase needs no re-run; a hand-resolved logic conflict re-runs once), then run "
                      "this again (never force)")
    pin_note = check_pin_is_released(upstream, top)
    _, head, _ = git("rev-parse", "HEAD", cwd=top)
    return {"top": top, "main_clone": main_clone, "branch": branch, "main": main,
            "upstream": upstream, "head": head, "pin_note": pin_note,
            "lands_on_main": main == cfg["main_branch"], "has_backlog": (top / cfg["backlog_dir"]).is_dir()}


def land(p):
    """Push and read the result back. Returns None when landed, else the reason."""
    top, upstream = p["top"], p["upstream"]
    if not ancestor("HEAD", upstream, top):
        rc, _, err = git("push", "-q", "origin", f"{p['branch']}:{p['main']}", cwd=top)
        if rc:
            return f"push to {upstream} failed: {err.splitlines()[0] if err else rc}"
    rc, _, err = git("fetch", "-q", "origin", p["main"], cwd=top)
    if rc:
        return f"pushed, but the re-fetch failed ({err}) — landing unverified; check {upstream} by hand"
    if not ancestor(p["head"], upstream, top):
        return f"{upstream} does not contain {p['head'][:7]} after the push"
    return None


def clean_up(p):
    """Remove the worktree and delete the branch, local then remote. Returns the
    steps that were skipped or failed (empty = all done)."""
    left = []
    main_clone, branch, upstream = p["main_clone"], p["branch"], p["upstream"]
    rc, _, err = git("worktree", "remove", str(p["top"]), cwd=main_clone)
    if rc:
        left.append(f"worktree {p['top']} not removed: {err}")
    else:
        _, tip, _ = git("rev-parse", f"refs/heads/{branch}", cwd=main_clone)
        if tip and ancestor(tip, upstream, main_clone):
            rc, _, err = git("branch", "-D", branch, cwd=main_clone)
            if rc:
                left.append(f"local branch {branch} not deleted: {err}")
        else:
            left.append(f"local branch {branch} kept — its tip is not on {upstream}")
    remote = f"origin/{branch}"
    if git("rev-parse", "--verify", "--quiet", remote, cwd=main_clone)[0] == 0:
        if ancestor(remote, upstream, main_clone):
            rc, _, err = git("push", "-q", "origin", "--delete", branch, cwd=main_clone)
            if rc:
                left.append(f"remote branch {branch} not deleted: {err}")
        else:
            left.append(f"remote branch {branch} kept — it carries commits not on {upstream}")
    return left


def close_landed(p):
    """Run the backfill off origin/<main> (`--isolated`, LANES-23), never in the main
    clone's own checkout. Returns (lines, ok); ([], True) when skipped."""
    if not p["lands_on_main"] or not p["has_backlog"]:   # judged on the landed tree; the main clone has not pulled yet
        return [], True
    script = Path(__file__).resolve().parent / "backlog_index.py"
    try:
        proc = subprocess.run([sys.executable, str(script), "--root", str(p["main_clone"]),
                               "--backfill", "--push", "--isolated"], cwd=p["main_clone"], capture_output=True,
                              text=True, encoding="utf-8", timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return [f"backfill did not run: {e}"], False
    lines = [l for l in (proc.stdout + proc.stderr).splitlines() if l.strip()]
    return lines, proc.returncode == 0


def main(argv=None):
    use_utf8_console()
    ap = argparse.ArgumentParser(description="lanes: land a lane's branch, verify, then clean up")
    ap.add_argument("--keep", action="store_true", help="land and verify; leave the worktree and the branch")
    ap.add_argument("--dry-run", action="store_true", help="run every check; push nothing, remove nothing")
    ap.add_argument("--no-close", action="store_true",
                    help="skip the post-landing backfill that closes the landed issue")
    ap.add_argument("--onto", default=None, metavar="BRANCH",
                    help="land on BRANCH instead of git.main_branch (a repo whose work integrates on another branch)")
    args = ap.parse_args(argv)
    try:
        p = plan(Path.cwd(), args.onto)
    except Refused as e:
        print(f"NOT LANDED — {e}. Nothing was pushed, removed or deleted.", file=sys.stderr)
        return NOT_LANDED
    short = p["head"][:7]
    if p["pin_note"]:
        print(p["pin_note"])
    if args.dry_run:
        print(f"dry run: {p['branch']} @ {short} fast-forwards {p['upstream']}; would push "
              f"{p['branch']}:{p['main']}" + ("" if args.keep else ", then remove the worktree and delete the branch"))
        return 0
    reason = land(p)
    if reason:
        print(f"NOT LANDED — {reason}. Nothing was removed or deleted.", file=sys.stderr)
        return NOT_LANDED
    print(f"landed: {p['branch']} @ {short} is on {p['upstream']}")
    status = 0
    if args.keep:
        print("kept: the worktree and the branch (--keep)")
    else:
        left = clean_up(p)
        for line in left:
            print(f"clean-up: {line}", file=sys.stderr)
        if left:
            status = CLEANUP_INCOMPLETE
        else:
            print(f"cleaned: worktree {p['top']} removed, branch {p['branch']} deleted")
    if not args.no_close:
        lines, ok = close_landed(p)
        for line in lines:
            print(f"close: {line}", file=sys.stdout if ok else sys.stderr)
        if not ok:
            print("close: not completed — the next startup's backfill is the backstop", file=sys.stderr)
            status = CLEANUP_INCOMPLETE
    return status


if __name__ == "__main__":
    sys.exit(main())
