"""Claim a lane: every named issue in one commit, pushed, or nothing at all.

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage (in the MAIN clone, on the main branch, on the operator's directive):
  python3 lanes_claim.py CORE-64 UI-40 INFRA-31 --files "api/x.py, tests/test_x.py"
  python3 lanes_claim.py INFRA-92 --behind INFRA-90     # extend a lane already claimed
  python3 lanes_claim.py INFRA-122 --next-in INFRA-112  # put an issue at the FRONT of a lane (LANES-49)
  python3 lanes_claim.py CORE-64 --dry-run
  python3 lanes_claim.py --resume CORE-64              # the same operator, a second machine (LANES-7)

`session-startup` step 8b and `worktree-increment` step 1 as one all-or-nothing
operation (LANES-9). Written by hand, the claim slipped twice in one lane: a named
ID was left out of the commit, and a named ID had no file on the main branch (it
existed only on an unabsorbed branch), so the session re-scoped the lane silently.
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

`--next-in <LANE>` (LANES-49) puts the named IDs at the front of a lane already claimed,
as the next to work: `--behind` only appends, so an issue found mid-lane that had to go
first was claimed bare, which opened a lane of its own and split the work across two cards.
LANE is a lane key (`INFRA-112@2026-10-12`) or any member's ID. Each new ID is RESERVED,
queued behind what the lane's first reservation was queued behind, and that reservation
is re-queued behind the last new ID -- so the order reads head, new, old next, the rest.
An ID this machine already claimed ALONE in another lane moves instead (the fix for a
lane opened by mistake): it takes this lane's `lane:` and keeps its own state; an ACTIVE
or PENDING one is allowed only into a lane with no issue being worked, and is named first.
Refused: a lane not in flight, any live member or moved ID whose marker another machine
wrote (the only markers rewritten are this machine's own), an ID already in the lane, one
that shares its lane with others, and the plain claim's refusals. A marker names a machine,
not a session, so a second session on THIS machine is held off another session's lane by
the protocol's rule (never write to another session's claim), not by this check.

`--resume <ID>` (LANES-7) re-homes an ACTIVE lane to THIS machine: the lane's operator
started it on another machine and continues it here (the other-platform half, say). Refused unless the marker names the same person (`short`) on a different machine
and its branch is on origin. It makes the worktree from `origin/<branch>`, rewrites only
the marker's timestamp and `on <machine>@<host>` (keeping the worktree, branch and expected
files, and appending where it was resumed from), and pushes that under the OK-free guard,
which allows exactly this rewrite of another machine's marker. It is the owner moving their
own lane, so INFRA-47's "never write to another session's claim" is not in play -- which is
also why another person's lane is refused outright.

Exit status: 0 claimed and pushed; 1 refused, nothing written or committed; 2 committed
but not pushed (the reason is printed; the commit is on local main).
"""
import argparse, datetime, re, socket, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import lanes_config as lc              # noqa: E402
import push_guard                      # noqa: E402

ACTIVE_LINE_RE = re.compile(r"^⏳ IN-PROGRESS \((?P<stamp>\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?), "
                            r"(?P<info>[^)]*)\) — \*\*ACTIVE LANE[^*]*\*\*(?P<tail>.*)$", re.M)

QUEUED_RE = re.compile(r"([Qq]ueued behind\s+)(?:\[\[)?[A-Z][A-Z0-9]*-\d+(?:\]\])?")

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
        tail = (f"Claimed as part of the {stamp[:10]} lane, queued behind {behind}. "
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


def with_lane(text, lane):
    """`text` with its frontmatter `lane:` set to `lane`, right after `status:`."""
    nl = "\r\n" if "\r\n" in text else "\n"
    head, sep, body = text.partition(f"{nl}---{nl}")
    fm = [l for l in head.split(nl) if not l.startswith("lane:")]
    at = next((i for i, l in enumerate(fm) if l.startswith("status:")), len(fm) - 1)
    fm.insert(at + 1, f"lane: {lane}")
    return nl.join(fm) + sep + body


def requeued(text, behind):
    """`text` with its claim marker queued behind `behind` -- the one phrase changed."""
    line = next((l for l in text.splitlines() if l.startswith("⏳ IN-PROGRESS")), None)
    if line is None:
        raise Refused("no claim marker to re-queue")
    new, n = QUEUED_RE.subn(lambda m: m.group(1) + behind, line, count=1)
    if not n:
        new = f"{line} Queued behind {behind}."
    return text.replace(line, new, 1)


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
        self.watched = []          # issues rewritten but not claimed (--next-in's re-queue)
        self.subject_line = None   # set by --next-in

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

    def origin_path(self, issue_id):
        """(the ID's one file on origin/<main>, None) or (None, the problem)."""
        project = issue_id.rsplit("-", 1)[0]
        _, names, _ = git("ls-tree", "--name-only", self.upstream,
                          f"{self.backlog}/{project}/", cwd=self.root)
        hits = [n for n in names.splitlines() if Path(n).name.startswith(f"{issue_id}-")]
        if len(hits) == 1:
            return hits[0], None
        return None, (f"{issue_id}: no file on {self.upstream} ({self.where_else(issue_id)})"
                      if not hits else f"{issue_id}: {len(hits)} files on {self.upstream}")

    def locate(self):
        """Every ID's file on origin/<main>, and every ID claimable."""
        problems = []
        for issue_id in self.ids + ([self.behind] if self.behind else []):
            rel, problem = self.origin_path(issue_id)
            if problem:
                problems.append(problem)
                continue
            self.paths[issue_id] = rel
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
            elif meta.get("type") == "epic":
                problems.append(f"{issue_id}: is an epic — claim its children; the epic reads in "
                                "progress while any of them is claimed (LANES-31)")
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
        """{rel path: new text} for every ID, in lane order."""
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
        if self.subject_line:
            return self.subject_line
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
            for issue_id in self.ids + self.watched:
                if self.paths[issue_id] in changed.splitlines():
                    git("reset", "-q", "--keep", "HEAD~1", cwd=self.root)
                    return None, (f"{issue_id} changed on {self.upstream} while this claim was in flight — "
                                  "this claim was withdrawn; re-read it before claiming again")
        return False, f"push rejected {attempts} times — the claim commit is on local `{self.main}`"


def resume(root, issue_id, path=None, now=None):
    """Re-home this operator's ACTIVE lane to this machine. Returns (exit code, message)."""
    try:
        claim = Claim(root, [issue_id], now=now)
        claim.position()
        claim.sync()
        claim.ids = []                    # locate() only resolves the path; no claimability checks
        claim.behind = None
        _, names, _ = git("ls-tree", "--name-only", claim.upstream,
                          f"{claim.backlog}/{issue_id.rsplit('-', 1)[0]}/", cwd=root)
        hits = [n for n in names.splitlines() if Path(n).name.startswith(f"{issue_id}-")]
        if len(hits) != 1:
            raise Refused(f"{issue_id}: no single file on {claim.upstream}")
        rel = hits[0]
        text = (root / rel).read_text(encoding="utf-8")
        if (frontmatter(text) or {}).get("status") != "in-progress":
            raise Refused(f"{issue_id}: not claimed — claim it instead")
        m = ACTIVE_LINE_RE.search(text)
        if not m:
            raise Refused(f"{issue_id}: no ACTIVE LANE marker — only a lane with a pushed branch can be resumed")
        author = push_guard.marker_author(m.group(0))
        me = claim.cfg["machine"]
        if push_guard.is_mine(author, me):
            raise Refused(f"{issue_id}: this machine already owns the lane — `git worktree add` its branch if the worktree is missing")
        if author[0] != (me["short"] or "").lower():
            raise Refused(f"{issue_id}: the lane is {author[0]}'s, not {me['short']}'s — "
                          "never write to another person's claim")
        br = re.search(r"branch ([A-Za-z0-9._/-]+)", m.group("info"))
        wt = re.search(r"worktree ([A-Za-z0-9._-]+)", m.group("info"))
        if not br:
            raise Refused(f"{issue_id}: the marker names no branch")
        branch = br.group(1)
        if git("fetch", "-q", "origin", branch, cwd=root)[0]:
            raise Refused(f"branch `{branch}` is not on origin — push it from {author[1]} first; "
                          "the branch is the hand-off")
        target = Path(path) if path else root.parent / (wt.group(1) if wt else f"{root.name}-{issue_id.lower()}")
        if target.exists():
            raise Refused(f"{target} already exists")
        if git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", cwd=root)[0] == 0:
            if not ancestor(branch, f"origin/{branch}", root):
                raise Refused(f"local `{branch}` has commits origin does not — push them, or delete the stale local branch")
            rc, _, err = git("worktree", "add", str(target), branch, cwd=root)
            if not rc:
                git("-C", str(target), "merge", "-q", "--ff-only", f"origin/{branch}", cwd=root)
        else:
            rc, _, err = git("worktree", "add", "--track", "-b", branch, str(target), f"origin/{branch}", cwd=root)
        if rc:
            raise Refused(f"git worktree add failed: {err}")
    except Refused as e:
        return NOT_CLAIMED, f"NOT RESUMED — {e}. Nothing was written."
    old_owner = re.search(r"session on (\S+?)(?:,|$)", m.group("info"))
    info = re.sub(r"^[^,]*'s session(?: on [^,]+)?", identity(claim.cfg), m.group("info"))
    line = (f"⏳ IN-PROGRESS ({claim.stamp}, {info}) — **ACTIVE LANE.**{m.group('tail')}"
            f" Resumed from {old_owner.group(1) if old_owner else author[0]} (claimed {m.group('stamp')}).")
    (root / rel).write_text(text.replace(m.group(0), line), encoding="utf-8", newline="")
    subject = f"docs(backlog): {issue_id} resumed on {me['id']} (worktree {target.name}, branch {branch})"
    err = push_guard.commit_paths(root, [rel], subject)
    if err:
        return NOT_PUSHED, f"worktree {target} made, but the marker commit failed: {err}"
    code, msg = push_guard.push(root, claim.cfg, push_guard.OK_FREE)
    if code:
        return NOT_PUSHED, f"worktree {target} made and the marker committed, not pushed — {msg}"
    return 0, f"resumed {issue_id} on {me['id']}: worktree {target}, branch {branch} ({msg})"


def main(argv=None):
    use_utf8_console()
    ap = argparse.ArgumentParser(description="lanes: claim a lane of backlog issues in one pushed commit")
    ap.add_argument("ids", nargs="*", metavar="ID", help="the lane's issues, in working order")
    ap.add_argument("--files", default=None,
                    help="the first issue's expected files, as the marker should list them")
    ap.add_argument("--behind", default=None, metavar="ID",
                    help="extend a claimed lane: every ID is RESERVED, chained behind this one")
    ap.add_argument("--dry-run", action="store_true", help="every check; print the markers, write nothing")
    ap.add_argument("--resume", default=None, metavar="ID",
                    help="re-home this operator's ACTIVE lane to this machine (LANES-7)")
    ap.add_argument("--path", default=None, help="with --resume: where to make the worktree")
    ap.add_argument("--next-in", default=None, metavar="LANE",
                    help="put the IDs at the FRONT of a claimed lane, next to work (LANES-49): a lane key "
                         "or any member's ID; an ID this machine claimed alone in another lane moves in")
    args = ap.parse_args(argv)
    if args.resume:
        if args.ids or args.behind or args.dry_run or args.next_in:
            ap.error("--resume takes one ID and no other claim options")
        root = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd())[1] or Path.cwd())
        code, msg = resume(root, args.resume.strip().upper(), path=args.path)
        print(msg, file=sys.stdout if code == 0 else sys.stderr)
        return code
    if not args.ids:
        ap.error("name at least one ID (or --resume ID)")
    ids = list(dict.fromkeys(i.strip().upper() for i in args.ids))
    if args.next_in:
        if args.behind or args.files:
            ap.error("--next-in takes IDs and --dry-run only: the IDs are RESERVED, and --behind appends instead")
        root = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd())[1] or Path.cwd())
        try:
            code, lines = next_in(root, ids, args.next_in.strip().upper(), dry_run=args.dry_run)
        finally:
            if not args.dry_run:
                push_guard.refresh_view(root)
        for line in lines:
            print(line, file=sys.stdout if code == 0 else sys.stderr)
        return code
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
    try:
        return _write_commit_push(root, claim, texts, ids, behind)
    finally:
        push_guard.refresh_view(root)       # claimed or restored, the bookmark shows it (LANES-11)


def _commit_push(root, claim, texts):
    """Write `texts`, `--check`, commit by explicit path, push. Returns (status, message):
    `refused` (nothing left written), `pushed`, or `local` (committed, not pushed)."""
    originals = {rel: (root / rel).read_bytes() for rel in texts}
    for rel, text in texts.items():
        with open(root / rel, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    ok, out = claim.check()
    if not ok:
        for rel, data in originals.items():
            (root / rel).write_bytes(data)
        return "refused", f"backlog --check failed; the files were restored.\n{out}"
    git("add", "--", *texts, cwd=root)
    rc, _, err = git("commit", "-q", "-m", claim.subject(), "--", *texts, cwd=root)
    if rc:
        for rel, data in originals.items():
            (root / rel).write_bytes(data)
        git("reset", "-q", "--", *texts, cwd=root)
        return "refused", f"git commit failed: {err}. The files were restored."
    pushed, msg = claim.push()
    if pushed is None:
        return "refused", f"{msg}."
    return ("pushed" if pushed else "local"), msg


def _next_in_rewrites(claim, bidx, issues, ids, target):
    """{rel path: new text} putting `ids` at the front of `target`'s lane, plus the lane
    key and {moved ID: its marker state}. Raises Refused before anything is written."""
    root, me = claim.root, claim.cfg["machine"]
    lanes = bidx.lanes_in_flight(issues)
    lane = (next((ln for ln in lanes if ln["key"] == target), None)
            or next((ln for ln in lanes if any(m["id"] == target for m in ln["members"])), None))
    if lane is None:
        raise Refused(f"no lane in flight is `{target}` or holds it — `--next-in` takes a lane key "
                      "(`<ID>@<YYYY-MM-DD>`) or any member's ID")
    by_id = {i["id"]: i for i in issues if i.get("id")}
    lane_of = {m["id"]: ln for ln in lanes for m in ln["members"] if m.get("status") == "in-progress"}

    def read(rel):
        text = (root / rel).read_text(encoding="utf-8")
        line = next((l for l in text.splitlines() if l.startswith("⏳ IN-PROGRESS")), "")
        author = push_guard.marker_author(line)
        return text, author if author and push_guard.is_mine(author, me) else None, author

    live = [m for m in lane["members"] if m.get("status") == "in-progress"]
    for m in live:
        _, mine, author = read(m["_path"])
        if not mine:
            who = (f"{author[0]}" + (f" on {author[1]}" if author[1] else "")) if author else "an unreadable marker"
            raise Refused(f"lane {lane['key']} holds {m['id']}, claimed by {who} — only the session "
                          "that owns a lane adds to it (`--resume` moves your own lane here first)")
    moved = {}
    for iid in ids:
        rel, problem = claim.origin_path(iid)
        if problem:
            raise Refused(problem)
        claim.paths[iid] = rel
        text, mine, _ = read(rel)
        meta = frontmatter(text) or {}
        status = meta.get("status")
        if iid in lane_of and lane_of[iid] is lane:
            raise Refused(f"{iid} is already in lane {lane['key']}")
        if status in CLOSED_STATES:
            raise Refused(f"{iid}: is `{status}`")
        if meta.get("type") == "epic":
            raise Refused(f"{iid}: is an epic — claim its children (LANES-31)")
        if git("status", "--porcelain", "--", rel, cwd=root)[1]:
            raise Refused(f"{iid}: {rel} has uncommitted changes")
        if status != "in-progress":
            continue
        if not mine:
            raise Refused(f"{iid}: already claimed by another session — never write to another session's claim")
        own = lane_of.get(iid)
        stray = [m["id"] for m in (own["members"] if own else [])
                 if m.get("status") == "in-progress" and m["id"] not in ids]
        if stray:
            raise Refused(f"{iid}: its lane {own['key']} also holds {', '.join(stray)} — name them too, "
                          "to move the whole lane, or land them first")
        moved[iid] = ((by_id.get(iid) or {}).get("_marker") or {}).get("state")

    working = [i for i in ids if moved.get(i) in ("active", "pending")]
    head = lane["head"] if (lane["head"].get("status") == "in-progress" and
                            (lane["head"].get("_marker") or {}).get("state") in ("active", "pending")) else None
    if working and head:
        raise Refused(f"{working[0]} is being worked and lane {lane['key']} already works {head['id']} — "
                      "a lane works one issue at a time; land or release one first")
    if len(working) > 1:
        raise Refused(f"{', '.join(working)} are each being worked — a lane works one issue at a time")
    if working and ids[0] != working[0]:
        raise Refused(f"name {working[0]} first: it is being worked, so it heads the lane")

    # The order the view reads is the queued-behind chain: the new IDs take the place of the
    # lane's first reservation, and that reservation is re-queued behind the last of them.
    reserved = [m for m in live if (m.get("_marker") or {}).get("state") == "reserved"]
    first = reserved[0] if reserved else None
    if first:
        prev = (first.get("_marker") or {}).get("behind") or (head or lane["lead"])["id"]
    else:
        prev = live[-1]["id"]
    who, texts = identity(claim.cfg), {}
    for iid in ids:
        rel = claim.paths[iid]
        text = (root / rel).read_text(encoding="utf-8")
        try:
            if iid not in moved:
                prior = (frontmatter(text) or {}).get("status")
                text = with_claim(text, marker(RESERVED, claim.stamp, who, behind=prev, prior=prior), lane["key"])
            else:
                if moved[iid] == "reserved":
                    text = requeued(text, prev)
                text = with_lane(text, lane["key"])
        except Refused as e:
            raise Refused(f"{iid}: {e}")
        texts[rel] = text
        prev = iid
    if first:
        rel = Path(first["_path"]).as_posix()
        claim.paths[first["id"]] = rel
        claim.watched.append(first["id"])
        texts[rel] = requeued((root / rel).read_text(encoding="utf-8"), prev)
    moved_note = f" (moved: {', '.join(moved)})" if moved else ""
    claim.subject_line = f"docs(backlog): {', '.join(ids)} next in lane {lane['key']}{moved_note}"
    return texts, lane["key"], moved, (first["id"] if first else None)


def next_in(root, ids, target, now=None, dry_run=False):
    """Put `ids` at the front of a claimed lane, next to work (LANES-49).
    Returns (exit code, [lines to print])."""
    import backlog_index as bidx    # the view's own lane grouping: "next" means what the view shows
    saved = None
    try:
        claim = Claim(root, list(ids), now=now)
        claim.position()
        claim.sync()
        values = bidx.settings(root)
        saved = {k: getattr(bidx, k, None) for k in values}
        bidx.apply(values)
        issues, _ = bidx.load_issues()
        texts, key, moved, requeue = _next_in_rewrites(claim, bidx, issues, ids, target)
    except Refused as e:
        return NOT_CLAIMED, [f"NOT CLAIMED — {e}. Nothing was written."]
    finally:
        if saved is not None:
            bidx.apply(saved)
    if dry_run:
        lines = []
        for rel, text in texts.items():
            line = next(l for l in text.splitlines() if l.startswith("⏳ IN-PROGRESS"))
            lines.append(f"would write {rel}\n  {line}")
        return 0, lines + [f"would commit: {claim.subject()}"]
    status, msg = _commit_push(root, claim, texts)
    if status == "refused":
        return NOT_CLAIMED, [f"NOT CLAIMED — {msg}"]
    lines = [f"next in lane {key}: {iid} ({'moved, ' + (moved[iid] or '?') if iid in moved else RESERVED})"
             for iid in ids]
    if requeue:
        lines.append(f"re-queued {requeue} behind {ids[-1]}")
    lines.append(f"committed: {claim.subject()}  ({msg})")
    return (0 if status == "pushed" else NOT_PUSHED), lines


def _write_commit_push(root, claim, texts, ids, behind):
    status, msg = _commit_push(root, claim, texts)
    if status == "refused":
        print(f"NOT CLAIMED — {msg}", file=sys.stderr)
        return NOT_CLAIMED
    pushed = status == "pushed"
    for issue_id in ids:
        kind = RESERVED if (behind or issue_id != ids[0]) else PENDING
        print(f"claimed {issue_id}: {kind}")
    print(f"committed: {claim.subject()}  ({msg})", file=sys.stdout if pushed else sys.stderr)
    return 0 if pushed else NOT_PUSHED


if __name__ == "__main__":
    sys.exit(main())
