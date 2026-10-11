"""Sync the main branch to origin, reconciling a tree a file-sync mirror has already updated.

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage (in the main clone, on the main branch):
  python3 lanes_pull.py                # startup's pull: fast-forward, or rebase local commits
  python3 lanes_pull.py --ff-only      # the increment's pull: refuse when local main has commits
  python3 lanes_pull.py --dry-run      # classify and print the plan; move nothing

Why (LANES-38). A repository can carry a directory that is BOTH git-tracked and mirrored
by a file-sync client (a cloud-drive folder junctioned into the tree). The same bytes
then travel on two channels, and the mirror is usually faster than the next pull. On
every machine that did not make the commit, the mirrored copy lands first: tracked files
show as modified, new files as untracked, and `git pull --rebase` refuses with "unstaged
changes" even though every one of those files is byte-identical to `origin/<main>`.
`rebase.autoStash` does not cover it (git refuses to overwrite an untracked file on
checkout whatever its content), and a stash deletes the untracked files for a moment,
which the mirror propagates to every other machine as a delete. The first machine to
receive, through the mirror, a fixture landing another machine had already committed sat
318 commits behind until the operator reset it by hand.

So the pull classifies the dirty tree before it refuses:

  1. Fetch `origin/<main>`. Refuse outside the main branch or inside a rebase or merge.
  2. Every dirty path (modified, staged, deleted, untracked-not-ignored) is compared to
     `origin/<main>` by blob hash, through the path's clean filters, so a line-ending
     phantom counts as identical:
       - identical to origin         -> RECONCILED: git is told the file is already there
       - untracked, not on origin    -> CARRIED: a new local file; stays untracked, as a
                                        plain pull would leave it
       - anything else               -> a BLOCKER: a genuine local change, named per path
  3. With no blockers: move the branch ref (`update-ref`, ORIG_HEAD set) and reset the
     index only, so a reconciled file is never written -- the mirror sees no change -- and
     check out just the paths origin changed that the mirror had NOT already delivered.
     Local commits (not `--ff-only`) are rebased first in a throwaway worktree, so the
     dirty tree is never asked to be clean; a conflict aborts and refuses, moving nothing.
  4. With blockers: refuse, listing them, exactly as `git pull --rebase` would -- but by
     path, and only for the paths that genuinely differ.

Exit status: 0 synced (or already up to date); 1 not synced -- nothing was moved.
"""
from __future__ import annotations

import argparse, os, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import lanes_config as lc              # noqa: E402

NOT_SYNCED = 1
RECONCILED, CARRIED, BLOCKER = "reconciled", "carried", "blocker"


def git(*args, cwd, stdin=None, raw=False):
    """(returncode, stdout, stderr); never raises. `raw` keeps stdout unstripped --
    a porcelain status row starts with a significant space."""
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, input=stdin, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)
    return proc.returncode, proc.stdout if raw else proc.stdout.strip(), proc.stderr.strip()


def ancestor(a, b, cwd):
    return git("merge-base", "--is-ancestor", a, b, cwd=cwd)[0] == 0


class Refused(Exception):
    pass


class Pull:
    def __init__(self, root: Path, ff_only=False, dry_run=False):
        self.root = root
        self.ff_only, self.dry_run = ff_only, dry_run
        loaded = lc.load(root)
        if loaded.parse_error:
            raise Refused(f"lanes config does not parse: {loaded.parse_error}")
        cfg = lc.resolve(loaded.raw, user_name=lc.git_user_name(root))
        self.main = cfg["main_branch"]
        self.upstream = f"origin/{self.main}"
        self.classes: dict[str, tuple[str, str]] = {}   # path -> (class, why)

    # -- 1 ------------------------------------------------------------------
    def position(self):
        rc, _, err = git("rev-parse", "--show-toplevel", cwd=self.root)
        if rc:
            raise Refused(f"not inside a git repository: {err}")
        for state, name in (("rebase-merge", "rebase"), ("rebase-apply", "rebase"),
                            ("MERGE_HEAD", "merge"), ("CHERRY_PICK_HEAD", "cherry-pick")):
            _, path, _ = git("rev-parse", "--git-path", state, cwd=self.root)
            if path and Path(self.root, path).exists():
                raise Refused(f"a {name} is in progress here -- finish or abort it first")
        _, branch, _ = git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.root)
        if branch != self.main:
            raise Refused(f"this checkout is on `{branch}`, not `{self.main}` -- the pull syncs the main branch")

    def fetch(self):
        rc, _, err = git("fetch", "-q", "origin", self.main, cwd=self.root)
        if rc:
            raise Refused(f"git fetch origin {self.main} failed: {err}")
        self.old = git("rev-parse", "HEAD", cwd=self.root)[1]
        self.new = git("rev-parse", self.upstream, cwd=self.root)[1]

    # -- 2 ------------------------------------------------------------------
    def dirty(self):
        """[(xy, path)] for every path the working tree or index differs from HEAD on,
        untracked-not-ignored included, renames off so every row is one path."""
        rc, out, err = git("status", "--porcelain=v1", "-z", "--untracked-files=all",
                           "--no-renames", cwd=self.root, raw=True)
        if rc:
            raise Refused(f"git status failed: {err}")
        rows = []
        for entry in out.split("\0"):
            if len(entry) < 4:
                continue
            rows.append((entry[:2], entry[3:]))
        return rows

    def upstream_blob(self, path):
        rc, sha, _ = git("rev-parse", "--verify", "-q", f"{self.upstream}:{path}", cwd=self.root)
        return sha if rc == 0 and sha else None

    def worktree_blob(self, path):
        full = self.root / path
        if not full.is_file():
            return None
        rc, sha, _ = git("hash-object", "--", path, cwd=self.root)
        return sha if rc == 0 else None

    def classify(self):
        for xy, path in self.dirty():
            if "U" in xy or xy in ("AA", "DD"):
                self.classes[path] = (BLOCKER, "unmerged")
                continue
            up = self.upstream_blob(path)
            if xy == "??":
                if up is None:
                    self.classes[path] = (CARRIED, f"new here, not on {self.upstream}")
                elif self.worktree_blob(path) == up:
                    self.classes[path] = (RECONCILED, f"untracked, identical to {self.upstream}")
                else:
                    self.classes[path] = (BLOCKER, f"untracked, differs from {self.upstream}")
                continue
            if "D" in xy and not (self.root / path).is_file():
                if up is None:
                    self.classes[path] = (RECONCILED, f"deleted here and on {self.upstream}")
                else:
                    self.classes[path] = (BLOCKER, f"deleted here, present on {self.upstream}")
                continue
            if up is None:
                self.classes[path] = (BLOCKER, f"changed here, not on {self.upstream}")
            elif self.worktree_blob(path) == up:
                self.classes[path] = (RECONCILED, f"identical to {self.upstream}")
            else:
                self.classes[path] = (BLOCKER, f"differs from {self.upstream}")

    def of(self, kind):
        return sorted(p for p, (k, _) in self.classes.items() if k == kind)

    # -- 3 ------------------------------------------------------------------
    def rebased_tip(self):
        """Rebase local commits onto origin in a throwaway worktree; the tip, or Refused.
        The main clone's files are never touched, so its dirty tree is no obstacle."""
        scratch = Path(tempfile.mkdtemp(prefix="lanes-pull-", dir=self.root.parent))
        scratch.rmdir()
        rc, _, err = git("worktree", "add", "-q", "--detach", str(scratch), "HEAD", cwd=self.root)
        if rc:
            raise Refused(f"could not make the scratch worktree for the rebase: {err}")
        try:
            rc, _, err = git("rebase", "-q", self.upstream, cwd=scratch)
            if rc:
                git("rebase", "--abort", cwd=scratch)
                raise Refused(f"rebasing local `{self.main}` onto {self.upstream} conflicts -- "
                              f"resolve it with the operator: {err.splitlines()[-1] if err else 'conflict'}")
            return git("rev-parse", "HEAD", cwd=scratch)[1]
        finally:
            git("worktree", "remove", "--force", str(scratch), cwd=self.root)
            shutil.rmtree(scratch, ignore_errors=True)

    def changed(self, old, new):
        """{path: status} between two commits, renames off."""
        rc, out, err = git("diff", "--name-status", "--no-renames", "-z", old, new, cwd=self.root)
        if rc:
            raise Refused(f"git diff {old[:7]}..{new[:7]} failed: {err}")
        parts = out.split("\0")
        return {parts[i + 1]: parts[i][0] for i in range(0, len(parts) - 1, 2) if parts[i]}

    def move_to(self, tip):
        """Point the branch at `tip` without writing a reconciled file, then bring in the
        rest of what origin changed."""
        rc, _, err = git("update-ref", "-m", f"lanes_pull: sync {self.main} to {self.upstream}",
                         f"refs/heads/{self.main}", tip, cwd=self.root)
        if rc:
            raise Refused(f"could not move refs/heads/{self.main}: {err}")
        rc, _, err = git("reset", "-q", cwd=self.root)          # index only; the tree is untouched
        if rc:
            raise Refused(f"git reset (index only) failed after moving the ref: {err}")
        git("update-ref", "ORIG_HEAD", self.old, cwd=self.root)   # after the reset, which rewrites it
        delivered = set(self.of(RECONCILED))
        to_checkout, to_delete = [], []
        for path, status in self.changed(self.old, tip).items():
            if path in delivered:
                continue
            (to_delete if status == "D" else to_checkout).append(path)
        if to_checkout:
            rc, _, err = git("checkout", "-q", "HEAD", "--pathspec-from-file=-", "--pathspec-file-nul",
                             cwd=self.root, stdin="\0".join(to_checkout) + "\0")
            if rc:
                raise Refused(f"checking out {len(to_checkout)} changed path(s) failed: {err}")
        for path in to_delete:
            full = self.root / path
            if full.is_file():
                full.unlink()
            parent = full.parent
            while parent != self.root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        return len(to_checkout), len(to_delete)

    def count(self, a, b):
        return int(git("rev-list", "--count", f"{a}..{b}", cwd=self.root)[1] or 0)

    # -- the whole thing ----------------------------------------------------
    def run(self, out):
        self.position()
        self.fetch()
        self.classify()
        blockers, reconciled, carried = self.of(BLOCKER), self.of(RECONCILED), self.of(CARRIED)
        up_to_date = ancestor(self.upstream, "HEAD", self.root)
        ahead = self.count(self.upstream, "HEAD")
        behind = self.count("HEAD", self.upstream)

        if up_to_date:
            left = len(blockers) + len(reconciled) + len(carried)
            out(f"pull: up to date at {self.old[:7]}" + (f" -- {ahead} local commit(s) not on {self.upstream}" if ahead else "")
                + (f"; {left} local change(s) left as they are" if left else ""))
            return 0
        if blockers:
            raise Refused(f"{len(blockers)} dirty path(s) differ from {self.upstream} -- commit, stash or "
                          "revert them with the operator, then retry:\n" + "\n".join(
                              f"    {p}  ({self.classes[p][1]})" for p in blockers))
        if ahead and self.ff_only:
            raise Refused(f"local `{self.main}` has {ahead} commit(s) {self.upstream} lacks (--ff-only) -- "
                          "someone left commits on the main branch; surface them")

        plan = (f"fast-forward {self.old[:7]}..{self.new[:7]} ({behind} commit(s))" if not ahead
                else f"rebase {ahead} local commit(s) onto {self.upstream} ({behind} commit(s) in)")
        if reconciled:
            plan += f"; {len(reconciled)} path(s) already identical to {self.upstream} are reconciled without a write"
        if carried:
            plan += f"; {len(carried)} new local file(s) stay untracked"
        if self.dry_run:
            out(f"pull (dry run): would {plan}")
            for p in reconciled:
                out(f"    reconcile  {p}")
            for p in carried:
                out(f"    carry      {p}")
            return 0

        tip = self.new if not ahead else self.rebased_tip()
        checked_out, deleted = self.move_to(tip)
        out(f"pull: {plan.replace('would ', '')}")
        out(f"pull: {checked_out} path(s) checked out, {deleted} removed, {len(reconciled)} reconciled, "
            f"{len(carried)} carried; ORIG_HEAD = {self.old[:7]}")
        residual = [p for xy, p in self.dirty() if xy != "??" or p not in set(carried)]
        if residual:
            out(f"pull: {len(residual)} path(s) still differ from HEAD after the sync -- read them: "
                + ", ".join(residual[:8]) + (" …" if len(residual) > 8 else ""))
        refresh_view(self.root, out)
        return 0


def refresh_view(root: Path, out) -> None:
    """Regenerate the main clone's bookmarked view after a sync (LANES-40).

    The sync is an `update-ref`, an index reset and a file checkout -- never a merge or
    a rewrite -- so the view hooks `post-merge` and `post-rewrite` do not fire for it, and
    `post-checkout` fires only when a path was checked out (a sync the mirror delivered in
    full checks out nothing). The hooks' promise, a view regenerated after ANY pull
    (LANES-11), is kept here, by the same call `view_hooks.py --hook` makes. Off when
    `backlog.view_mode = "serve"` or the repo has no backlog dir; never fails the sync."""
    try:
        import view_hooks as vh
        import backlog_index as bidx
        if not vh.enabled(str(root)):
            return
        bidx.configure(root)
        if not (root / bidx.BACKLOG_REL).is_dir():
            return
        html = bidx.refresh_main_view()
        if html:
            out(f"pull: backlog view refreshed ({html})")
    except Exception as e:                                    # noqa: BLE001 -- a view is never worth a failed sync
        out(f"pull: backlog view not refreshed ({e})")


def main(argv=None):
    use_utf8_console()
    ap = argparse.ArgumentParser(description="lanes: sync the main branch, reconciling a mirror-delivered tree")
    ap.add_argument("--root", help="repository (default: the one containing the cwd)")
    ap.add_argument("--ff-only", action="store_true", help="refuse when local main has commits origin lacks")
    ap.add_argument("--dry-run", action="store_true", help="classify and print the plan; move nothing")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve() if a.root else Path.cwd()
    rc, top, err = git("rev-parse", "--show-toplevel", cwd=root)
    if rc:
        print(f"pull: REFUSED -- not inside a git repository: {err}", file=sys.stderr)
        return NOT_SYNCED
    try:
        return Pull(Path(top), ff_only=a.ff_only, dry_run=a.dry_run).run(print)
    except Refused as e:
        print(f"pull: REFUSED -- {e}", file=sys.stderr)
        return NOT_SYNCED


if __name__ == "__main__":
    sys.exit(main())
