"""Claim a slice: every named issue in one commit, pushed, or nothing at all.

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage (in the MAIN clone, on the main branch, on the operator's directive):
  python3 lanes_claim.py CORE-64 UI-40 INFRA-31 --files "api/x.py, tests/test_x.py"
  python3 lanes_claim.py INFRA-92 --behind INFRA-90     # extend a lane already claimed
  python3 lanes_claim.py CORE-64 --dry-run

`session-startup` step 8b and `worktree-increment` step 1 as one all-or-nothing
operation (LANES-9). Written by hand, the claim slipped twice in one slice: a named
ID was left out of the commit, and a named ID had no file on the main branch (it
existed only on an unabsorbed branch), so the session re-scoped the slice silently.
Hand-written markers also drift from the spelling the doctor reads.

  1. Fetch and fast-forward the main branch. Refuse when this is not the main clone,
     not the main branch, or local main has diverged from origin.
  2. Refuse unless EVERY ID has a file on `origin/<main>`. A missing one is named with
     the refs where it does exist, so a re-scope is the operator's call, not a silent one.
  3. Refuse any ID that is already `in-progress` (never write to another session's
     claim), `verified` or `closed`, or whose file has uncommitted changes.
  4. Write `status: in-progress` and the marker on every ID: the first `WORKTREE
     PENDING` with its expected files, each later one `RESERVED, NOT STARTED` queued
     behind the one before it. With `--behind <ID>`, every named ID is RESERVED,
     chained behind that lane. Timestamps are local, with minutes.
  5. `backlog_index.py --check`, one commit staged by explicit path, the main-direct
     guard over everything ahead of origin, push. A rejected push re-fetches, rebases
     and re-checks 2-3 rather than forcing; a concurrent claim of the same ID
     conflicts, and this claim is withdrawn.

Exit status: 0 claimed and pushed; 1 refused, nothing written or committed; 2 committed
but not pushed (the reason is printed; the commit is on local main).
"""
import argparse, datetime, re, socket, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import lanes_config as lc              # noqa: E402
import push_guard                      # noqa: E402

NOT_CLAIMED, NOT_PUSHED = 1, 2
PENDING, RESERVED = "WORKTREE PENDING", "RESERVED, NOT STARTED"
CLOSED_STATES = ("verified", "closed")


def _now():
    return datetime.datetime.now()


class Refused(Exception):
    """A check failed before anything was written."""


def git(*args, cwd):
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def ancestor(a, b, cwd):
    return git("merge-base", "--is-ancestor", a, b, cwd=cwd)[0] == 0


def frontmatter(text):
    """{key: raw value} from the flat frontmatter block, or None."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    meta = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return meta
        key, sep, val = line.partition(":")
        if sep:
            meta[key.strip()] = val.strip()
    return None


def identity(cfg):
    """`<Short>'s session on <machine id>@<host>` -- the marker's author."""
    host = socket.gethostname().split(".")[0] or "host"
    short = cfg["machine"]["short"] or "operator"
    return f"{short[:1].upper()}{short[1:]}'s session on {cfg['machine']['id']}@{host}"


def marker(kind, stamp, who, behind=None, files=None, prior=None):
    """The ⏳ line, spelled exactly as `lanes_doctor.KIND_RE` reads it."""
    if kind == PENDING:
        tail = ("Claim pushed; worktree not yet created. Expected files: "
                + (files or "(named when the lane goes ACTIVE)") + ".")
    else:
        tail = (f"Claimed as part of the {stamp[:10]} slice, queued behind {behind}. "
                "No worktree yet and no files touched.")
    if prior and prior != "open":
        tail += f" Prior status: `{prior}`."
    return f"⏳ IN-PROGRESS ({stamp}, {who}) — **{kind}.** {tail}"


def with_claim(text, line, lane=None):
    """`status: in-progress` (+ `lane:`) + the marker at the top of Current status."""
    nl = "\r\n" if "\r\n" in text else "\n"
    head, sep, body = text.partition(f"{nl}---{nl}")
    if not sep or not head.startswith("---"):
        raise Refused("no frontmatter block")
    fm = []
    for l in head.split(nl):
        if l.startswith("lane:"):
            continue                      # rewritten below, never duplicated
        fm.append("status: in-progress" if l.startswith("status:") else l)
        if lane and l.startswith("status:"):
            fm.append(f"lane: {lane}")    # LANES-10: the lane's recorded identity
    section = f"{nl}## Current status{nl}"
    if section not in body:
        raise Refused("no `## Current status` section")
    pre, _, post = body.partition(section)
    post = post.lstrip("\r\n")
    return nl.join(fm) + sep + pre + section + nl + line + nl + nl + post


class Claim:
    def __init__(self, root, ids, behind=None, files=None, now=None):
        self.root = root
        self.ids = ids
        self.behind = behind
        self.files = files
        loaded = lc.load(root)
        if loaded.parse_error:
            raise Refused(f"lanes config does not parse: {loaded.parse_error}")
        self.cfg = lc.resolve(loaded.raw, user_name=lc.git_user_name(root))
        self.main = self.cfg["main_branch"]
        self.upstream = f"origin/{self.main}"
        self.backlog = self.cfg["backlog_dir"].strip("/")
        self.stamp = (now or _now()).strftime("%Y-%m-%d %H:%M")
        self.paths = {}

    # -- 1 ------------------------------------------------------------------
    def position(self):
        rc, top, err = git("rev-parse", "--show-toplevel", cwd=self.root)
        if rc:
            raise Refused(f"not inside a git repository: {err}")
        _, git_dir, _ = git("rev-parse", "--absolute-git-dir", cwd=self.root)
        _, common, _ = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=self.root)
        if Path(git_dir).resolve() != Path(common).resolve():
            raise Refused("this is a lane worktree — a claim is made in the main clone, before the worktree exists")
        _, branch, _ = git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.root)
        if branch != self.main:
            raise Refused(f"the main clone is on `{branch}`, not `{self.main}`")

    def sync(self):
        rc, _, err = git("fetch", "-q", "origin", self.main, cwd=self.root)
        if rc:
            raise Refused(f"git fetch origin {self.main} failed: {err}")
        self.base = git("rev-parse", self.upstream, cwd=self.root)[1]
        if ancestor(self.upstream, "HEAD", self.root):
            return
        if ancestor("HEAD", self.upstream, self.root):
            rc, _, err = git("merge", "-q", "--ff-only", self.upstream, cwd=self.root)
            if rc:
                raise Refused(f"fast-forward to {self.upstream} failed: {err}")
            return
        raise Refused(f"local `{self.main}` and {self.upstream} have diverged — "
                      "another session may have an unpushed commit here; wait for it, then retry")

    # -- 2, 3 ---------------------------------------------------------------
    def where_else(self, issue_id):
        project = issue_id.rsplit("-", 1)[0]
        rc, shas, _ = git("log", "--all", "--format=%H", "--",
                          f"{self.backlog}/{project}/{issue_id}-*.md", cwd=self.root)
        if rc or not shas:
            return "it exists on no ref"
        _, refs, _ = git("branch", "-a", "--format=%(refname:short)", "--contains",
                         shas.splitlines()[-1], cwd=self.root)
        refs = [r for r in refs.splitlines() if r and not r.endswith("/HEAD")]
        return ("only on " + ", ".join(f"`{r}`" for r in refs[:3])
                + (f" +{len(refs) - 3} more" if len(refs) > 3 else "")
                + " — absorb or land it first") if refs else "it exists on no current branch"

    def locate(self):
        """Every ID's file on origin/<main>, and every ID claimable."""
        problems = []
        for issue_id in self.ids + ([self.behind] if self.behind else []):
            project = issue_id.rsplit("-", 1)[0]
            _, names, _ = git("ls-tree", "--name-only", self.upstream,
                              f"{self.backlog}/{project}/", cwd=self.root)
            hits = [n for n in names.splitlines() if Path(n).name.startswith(f"{issue_id}-")]
            if len(hits) != 1:
                problems.append(f"{issue_id}: no file on {self.upstream} ({self.where_else(issue_id)})"
                                if not hits else f"{issue_id}: {len(hits)} files on {self.upstream}")
                continue
            self.paths[issue_id] = hits[0]
        if problems:
            raise Refused("; ".join(problems))
        for issue_id in self.ids:
            rel = self.paths[issue_id]
            meta = frontmatter((self.root / rel).read_text(encoding="utf-8"))
            status = (meta or {}).get("status")
            if meta is None:
                problems.append(f"{issue_id}: unparseable frontmatter")
            elif status == "in-progress":
                problems.append(f"{issue_id}: already claimed — never write to another session's claim")
            elif status in CLOSED_STATES:
                problems.append(f"{issue_id}: is `{status}`")
            elif git("status", "--porcelain", "--", rel, cwd=self.root)[1]:
                problems.append(f"{issue_id}: {rel} has uncommitted changes")
        if self.behind:
            meta = frontmatter((self.root / self.paths[self.behind]).read_text(encoding="utf-8")) or {}
            if meta.get("status") != "in-progress":
                problems.append(f"--behind {self.behind}: not a claimed lane (status `{meta.get('status')}`)")
        if problems:
            raise Refused("; ".join(problems))

    # -- 4 ------------------------------------------------------------------
    def lane(self):
        """`<lead-ID>@<YYYY-MM-DD>` -- or, with --behind, the extended lane's own value.

        A lead claimed before the field existed has none; its key is derived the way
        `backlog_index.lanes_in_flight` derives one from a marker, `<ID>@<claim date>`,
        so the new reservation groups with it.
        """
        if not self.behind:
            return f"{self.ids[0]}@{self.stamp[:10]}"
        text = (self.root / self.paths[self.behind]).read_text(encoding="utf-8")
        recorded = (frontmatter(text) or {}).get("lane")
        if recorded and recorded not in ("null", "~"):
            return recorded
        m = re.search(r"⏳ IN-PROGRESS \((\d{4}-\d{2}-\d{2})", text)
        return f"{self.behind}@{m.group(1) if m else self.stamp[:10]}"

    def rewrites(self):
        """{rel path: new text} for every ID, in slice order."""
        who, out, prev = identity(self.cfg), {}, self.behind
        lane = self.lane()
        for issue_id in self.ids:
            rel = self.paths[issue_id]
            text = (self.root / rel).read_text(encoding="utf-8")
            prior = frontmatter(text).get("status")
            kind = RESERVED if prev else PENDING
            line = marker(kind, self.stamp, who, behind=prev, files=self.files, prior=prior)
            try:
                out[rel] = with_claim(text, line, lane)
            except Refused as e:
                raise Refused(f"{issue_id}: {e}")
            prev = issue_id
        return out

    def subject(self):
        if self.behind:
            return f"docs(backlog): reserve {', '.join(self.ids)} behind {self.behind}"
        rest = f", reserve {', '.join(self.ids[1:])}" if len(self.ids) > 1 else ""
        return f"docs(backlog): claim {self.ids[0]} (WORKTREE PENDING){rest}"

    # -- 5 ------------------------------------------------------------------
    def check(self):
        script = Path(__file__).resolve().parent / "backlog_index.py"
        proc = subprocess.run([sys.executable, str(script), "--root", str(self.root), "--check"],
                              cwd=self.root, capture_output=True, text=True, encoding="utf-8")
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()

    def stray(self):
        return push_guard.stray_paths(self.root, self.cfg, push_guard.CLAIM)

    def push(self, attempts=3):
        for _ in range(attempts):
            stray = self.stray()
            if stray:
                return False, (f"local `{self.main}` carries commits outside git.main_direct_paths "
                               f"({stray[0]}) — push them with the operator's OK, then this claim goes with them")
            rc, _, err = git("push", "-q", "origin", f"HEAD:{self.main}", cwd=self.root)
            if rc == 0:
                return True, f"pushed to {self.upstream}"
            if git("fetch", "-q", "origin", self.main, cwd=self.root)[0]:
                return False, f"push rejected and the re-fetch failed: {err}"
            rc, _, rerr = git("rebase", "-q", "--autostash", self.upstream, cwd=self.root)
            if rc:
                git("rebase", "--abort", cwd=self.root)
                git("reset", "-q", "--keep", "HEAD~1", cwd=self.root)
                git("merge", "-q", "--ff-only", self.upstream, cwd=self.root)
                return None, ("another session changed these issue files first (the rebase conflicted) — "
                              "this claim was withdrawn; re-read the issues before claiming again")
            _, tip, _ = git("rev-parse", self.upstream, cwd=self.root)
            changed = git("diff", "--name-only", self.base, tip, "--", *self.paths.values(), cwd=self.root)[1]
            self.base = tip
            for issue_id in self.ids:
                if self.paths[issue_id] in changed.splitlines():
                    git("reset", "-q", "--keep", "HEAD~1", cwd=self.root)
                    return None, (f"{issue_id} changed on {self.upstream} while this claim was in flight — "
                                  "this claim was withdrawn; re-read it before claiming again")
        return False, f"push rejected {attempts} times — the claim commit is on local `{self.main}`"


def main(argv=None):
    use_utf8_console()
    ap = argparse.ArgumentParser(description="lanes: claim a slice of backlog issues in one pushed commit")
    ap.add_argument("ids", nargs="+", metavar="ID", help="the slice, in working order")
    ap.add_argument("--files", default=None,
                    help="the first issue's expected files, as the marker should list them")
    ap.add_argument("--behind", default=None, metavar="ID",
                    help="extend a claimed lane: every ID is RESERVED, chained behind this one")
    ap.add_argument("--dry-run", action="store_true", help="every check; print the markers, write nothing")
    args = ap.parse_args(argv)
    ids = list(dict.fromkeys(i.strip().upper() for i in args.ids))
    behind = args.behind.strip().upper() if args.behind else None
    try:
        root = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd())[1] or Path.cwd())
        claim = Claim(root, ids, behind=behind, files=args.files)
        if behind in ids:
            raise Refused(f"--behind {behind} is also named as an ID")
        claim.position()
        claim.sync()
        claim.locate()
        texts = claim.rewrites()
    except Refused as e:
        print(f"NOT CLAIMED — {e}. Nothing was written.", file=sys.stderr)
        return NOT_CLAIMED
    if args.dry_run:
        for rel, text in texts.items():
            line = next(l for l in text.splitlines() if l.startswith("⏳ IN-PROGRESS"))
            print(f"would claim {rel}\n  {line}")
        print(f"would commit: {claim.subject()}")
        return 0
    originals = {rel: (root / rel).read_bytes() for rel in texts}
    for rel, text in texts.items():
        with open(root / rel, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    ok, out = claim.check()
    if not ok:
        for rel, data in originals.items():
            (root / rel).write_bytes(data)
        print(f"NOT CLAIMED — backlog --check failed; the files were restored.\n{out}", file=sys.stderr)
        return NOT_CLAIMED
    git("add", "--", *texts, cwd=root)
    rc, _, err = git("commit", "-q", "-m", claim.subject(), "--", *texts, cwd=root)
    if rc:
        for rel, data in originals.items():
            (root / rel).write_bytes(data)
        git("reset", "-q", "--", *texts, cwd=root)
        print(f"NOT CLAIMED — git commit failed: {err}. The files were restored.", file=sys.stderr)
        return NOT_CLAIMED
    pushed, msg = claim.push()
    if pushed is None:
        print(f"NOT CLAIMED — {msg}.", file=sys.stderr)
        return NOT_CLAIMED
    for issue_id in ids:
        kind = RESERVED if (behind or issue_id != ids[0]) else PENDING
        print(f"claimed {issue_id}: {kind}")
    print(f"committed: {claim.subject()}  ({msg})", file=sys.stdout if pushed else sys.stderr)
    return 0 if pushed else NOT_PUSHED


if __name__ == "__main__":
    sys.exit(main())
