"""Generate the local backlog views (INDEX.md + index.html) from per-issue
frontmatter, print the aged report, check the issue files for what git can't, or
close verified issues by backfilling their resolving commit.

Part of the `lanes` plugin. Read/write, stdlib-only, runs on any machine with no
virtualenv. Status lives in YAML frontmatter on one file per issue, so indexing is a
glob + parse: no prose regex, no positional IDs.

Usage (from anywhere inside the repo; `--root` overrides):
  python3 backlog_index.py             # (re)write both local views under <backlog.dir>/
  python3 backlog_index.py --open      # ...and open the sortable HTML view in a browser
  python3 backlog_index.py --check     # exit 1 on any backlog integrity problem
  python3 backlog_index.py --report    # aged operator view to stdout
  python3 backlog_index.py --report --who <short>|both
  python3 backlog_index.py --serve     # serve the view, re-parsing on every request
  python3 backlog_index.py --backfill [--dry-run] [--commit]   # the certifying machine only

Configuration comes from `.claude/lanes/config.toml` (see lanes_config.py), resolved
ONCE at import into module globals -- PROJECTS, TYPES, PRIORITIES, ASSIGNEES, REPORTERS,
DOCS_LANE_PREFIXES, CLAIM_MARKER_EXEMPT, RESOLUTION_CUTOVER, VIEW_PORT, MAIN_BRANCH,
MACHINE -- so a test can `monkeypatch.setattr` any of them. Statuses, resolutions and
the claim-age floor are protocol constants, never configuration.

Two views, one parse. INDEX.md is a flat Markdown table (greppable, diffable);
index.html is the same rows made sortable and filterable in a browser. Both are
GENERATED and must stay out of git: every concurrent lane rewrites them, so a tracked
copy conflicts at every rebase. The issue files are the source of truth.

--check reports:
  * structural problems -- duplicate IDs, bad frontmatter, id/filename/directory
    mismatch, out-of-vocabulary enum values;
  * orphaned claims -- `status: in-progress` and the body IN-PROGRESS marker must
    travel together (either half alone poisons the worktree conflict scan);
  * orphaned commit citations -- a `commit:` hash that is not an ancestor of HEAD. A
    rebase before push rewrites every hash cited since the branch point, and the
    orphan still RESOLVES locally (reflog) while being a dead link on every other
    clone. Cite the commit SUBJECT in the Resolution prose; fill the hash only once
    the commit is on the main branch;
  * unresolvable verified issues -- `status: verified` must carry a filled Resolution
    whose cited commit subject is on HEAD (a dirty file is exempt from the subject
    half: its resolving commit is the one about to be made);
  * undocumented verified issues -- a verified issue whose change touched anything
    outside DOCS_LANE_PREFIXES must carry a `Docs:` line in its Resolution: the doc
    edited, the DOC issue queued, or "nothing -- no documented behavior changed";
  * dangling epics and resolution/status disagreements.

The `verified` status and --backfill. A worktree lane cannot know its resolving
commit's hash: the close rides IN that commit, and the pre-push rebase rewrites it
anyway. So the lane marks the issue `verified` (Resolution filled, the SUBJECT cited
in backticks, `commit:` null) and pushes. The certifying machine's session startup --
after the pull -- runs --backfill, which finds each verified issue's resolving commit
on HEAD by the exact subject it cites, fills `commit:`, and flips it to `closed`. One
writer, one mechanical pass. The script refuses to backfill on a machine whose
operator row does not certify; in solo mode every machine certifies.
"""
import argparse, datetime, html, re, subprocess, sys, webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import lanes_config as lc              # noqa: E402

# ---- protocol constants: read by name below and in the skills; never config ----
STATUSES = tuple(lc.STATUSES)
LIVE_STATUSES = tuple(lc.LIVE_STATUSES)
RESOLUTIONS = tuple(lc.RESOLUTIONS)
STATUS_RANK = {s: i for i, s in enumerate(STATUSES)}


def settings(root=None, raw=None):
    """Resolve the config for `root` into the module globals this script reads.

    ONE resolution, flat values -- so `monkeypatch.setattr(bidx, "ROOT", ...)` and
    friends keep working exactly as they did when these were literals. `root` None
    means the repo containing the cwd (or the cwd itself outside a repo); `raw`
    None means read `<root>/.claude/lanes/config.toml` (missing = defaults = solo).
    """
    root = Path(root) if root is not None else (lc.repo_root() or Path.cwd())
    if raw is None:
        raw = lc.load(root=root).raw
    cfg = lc.resolve(raw)
    backlog_rel = cfg["backlog_dir"].strip("/")
    ops = cfg["operators"]
    certifiers = [r["short"] for r in ops if r.get("certifies")]
    machine = cfg["machine"]
    if cfg["solo"]:
        certifier_label = "your"
    elif certifiers:
        certifier_label = f"{certifiers[0]}'s"
    else:
        certifier_label = "the certifying operator's"
    editors = [r["short"] for r in ops if r.get("may_edit_code", True)]
    default_assignee = (machine["short"] if cfg["solo"] else (editors[0] if editors else cfg["assignees"][0]))
    return {
        "ROOT": root,
        "BACKLOG_REL": backlog_rel,
        "BACKLOG": root / backlog_rel,
        "INDEX": root / backlog_rel / "INDEX.md",
        "HTML_VIEW": root / backlog_rel / "index.html",
        "REPO_NAME": root.name,
        "PROJECTS": tuple(cfg["projects"]),
        "TYPES": tuple(cfg["types"]),
        "PRIORITIES": tuple(cfg["priorities"]),
        "ASSIGNEES": tuple(cfg["assignees"]),
        "REPORTERS": tuple(cfg["reporters"]),
        "DEFAULT_ASSIGNEE": default_assignee,
        "RESOLUTION_CUTOVER": cfg["resolution_required_from"],   # None = always required
        "DOCS_LANE_PREFIXES": tuple(cfg["docs_lane_prefixes"]),
        "CLAIM_MARKER_EXEMPT": set(cfg["claim_marker_exempt"]),
        "VIEW_PORT": cfg["view_port"],
        "MAIN_BRANCH": cfg["main_branch"],
        "MACHINE": machine,
        "SOLO": cfg["solo"],
        "CERTIFIER_LABEL": certifier_label,
        "PRIORITY_RANK": {p: i for i, p in enumerate(cfg["priorities"])},
    }


def apply(values):
    """Assign a settings() dict onto this module."""
    for k, v in values.items():
        globals()[k] = v


def configure(root=None, raw=None):
    apply(settings(root, raw))


configure()


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_frontmatter(text):
    """Flat YAML only: `key: value` lines and `links: [A, B]`. Returns (meta, body)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    meta = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1:])
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            return None, text  # not the flat shape we write; treat as unparseable
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val in ("null", "~", ""):
            meta[key] = None
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            meta[key] = [_unquote(x) for x in inner.split(",") if x.strip()] if inner else []
        else:
            meta[key] = _unquote(val)
    return None, text  # no closing fence


def issue_title(body, issue_id):
    for line in body.split("\n"):
        m = re.match(r"^# +(.+)$", line)
        if m:
            t = m.group(1).strip()
            # The H1 convention is "# <ID> — <title>"; strip the ID half.
            t = re.sub(rf"^{re.escape(issue_id)}\s*[—:-]\s*", "", t)
            return t
    return "(untitled)"


def load_issues():
    """Parse every <backlog.dir>/<PROJECT>/*.md. Returns (issues, problems)."""
    issues, problems = [], []
    seen_ids = {}
    for path in sorted(BACKLOG.glob("*/*.md")):
        rel = path.relative_to(ROOT)
        project_dir = path.parent.name
        if project_dir not in PROJECTS:
            problems.append(f"{rel}: directory {project_dir!r} is not a project ({', '.join(PROJECTS)})")
            continue
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        if meta is None:
            problems.append(f"{rel}: missing or unparseable frontmatter")
            continue
        iid = meta.get("id") or ""
        expected_prefix = f"{project_dir}-"
        if not iid.startswith(expected_prefix):
            problems.append(f"{rel}: id {iid!r} doesn't match project directory {project_dir}")
        if not path.name.startswith(iid + "-") and path.stem != iid:
            problems.append(f"{rel}: filename doesn't start with its id {iid!r}")
        if iid in seen_ids:
            problems.append(f"{rel}: DUPLICATE id {iid} (also {seen_ids[iid]})")
        seen_ids[iid] = rel
        for field, allowed in (("type", TYPES), ("status", STATUSES), ("priority", PRIORITIES)):
            if meta.get(field) not in allowed:
                problems.append(f"{rel}: {field}={meta.get(field)!r} not in {allowed}")
        for field, allowed in (("assignee", ASSIGNEES), ("reported_by", REPORTERS),
                               ("resolution", RESOLUTIONS)):
            if meta.get(field) is not None and meta.get(field) not in allowed:
                problems.append(f"{rel}: {field}={meta.get(field)!r} not in {allowed} (or null)")
        meta.setdefault("assignee", None)
        meta.setdefault("reported_by", None)
        meta.setdefault("resolution", None)
        meta.setdefault("blocked_on", None)
        meta.setdefault("opened", None)
        meta.setdefault("closed", None)
        meta.setdefault("commit", None)
        meta.setdefault("links", [])
        meta.setdefault("epic", None)
        meta["_path"] = rel
        meta["_title"] = issue_title(body, iid)
        issues.append(meta)
    return issues, problems


def sort_key(it):
    return (PROJECTS.index(it["project"]) if it.get("project") in PROJECTS else 99,
            PRIORITY_RANK.get(it.get("priority"), 9),
            STATUS_RANK.get(it.get("status"), 9),
            it.get("opened") or "9999",
            it.get("id") or "")


IN_PROGRESS_MARKER = "IN-PROGRESS"
# CLAIM_MARKER_EXEMPT comes from config (`backlog.claim_marker_exempt`): an issue
# whose body legitimately QUOTES a historical marker would otherwise read as
# claimed forever.
HASH_RE = re.compile(r"^[0-9a-f]{7,40}$")


def orphaned_claims(issues):
    """Issues whose frontmatter claim and body ⏳ marker disagree.

    The worktree-increment skill sets BOTH at claim time and clears BOTH at
    close. A stale frontmatter `in-progress` misreports the queue to the other
    operator; a stale body marker fakes a conflict in the next lane's scan.
    Returns a list of human-readable problem strings.
    """
    out = []
    for it in issues:
        iid = it.get("id")
        if iid in CLAIM_MARKER_EXEMPT:
            continue
        has_marker = IN_PROGRESS_MARKER in (ROOT / it["_path"]).read_text(encoding="utf-8")
        claimed = it.get("status") == "in-progress"
        if has_marker != claimed:
            out.append(f"{it['_path']}: status={it.get('status')!r} but body marker "
                       f"{'present' if has_marker else 'absent'} — claim and marker must agree")
    return out


def reachable_commits():
    """Full hashes of every commit reachable from HEAD, or None if git can't say.

    None (not an empty set) so callers can tell "no git here" from "nothing is
    reachable" and degrade to no check rather than flagging every citation.
    """
    try:
        proc = subprocess.run(["git", "rev-list", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def orphaned_commit_citations(issues, reachable=None):
    """`commit:` hashes that no commit reachable from HEAD begins with.

    This is the rebase signature (ADMIN-6). An issue closed in a worktree cites
    its resolving commit; a rebase onto a moved origin/main rewrites that commit,
    and the OLD hash keeps resolving locally through the reflog — `git cat-file
    -e` passes, `git log --oneline <hash>` even prints the right subject — while
    on the other operator's clone it has never existed. The UI-12 lane shipped
    exactly that on 2026-09-01 (`cdc29e0` → `5d17435`), caught by hand.

    Ancestry is the check that works, so this asks "does any commit on HEAD's
    history start with this short hash?". `reachable` is injectable for tests;
    None means ask git, and if git can't answer the check is skipped (returns
    []) rather than failing on a machine without a repo.
    """
    if reachable is None:
        reachable = reachable_commits()
    if reachable is None:
        return []
    out = []
    for it in issues:
        h = it.get("commit")
        if not h:
            continue
        h = str(h).strip().lower()
        if not HASH_RE.match(h):
            out.append(f"{it['_path']}: commit={it.get('commit')!r} is not a git hash")
            continue
        if not any(full.startswith(h) for full in reachable):
            out.append(f"{it['_path']}: commit {h} is not an ancestor of HEAD — "
                       "rewritten by a rebase? cite the commit SUBJECT in the Resolution "
                       "and set commit: null (or the post-rebase hash once it is on origin/main)")
    return out


RESOLUTION_STUB = "(Fill on close:"
BACKTICKED_RE = re.compile(r"`([^`\n]+)`")


def resolution_section(body):
    """Text of the `## Resolution` section (up to the next H2), or None if absent."""
    m = re.search(r"^## +Resolution[ \t]*$", body, flags=re.M)
    if not m:
        return None
    rest = body[m.end():]
    nxt = re.search(r"^## ", rest, flags=re.M)
    return rest[:nxt.start()] if nxt else rest


def resolution_is_filled(body):
    sec = resolution_section(body)
    if sec is None:
        return False
    sec = sec.strip()
    return bool(sec) and not sec.startswith(RESOLUTION_STUB)


def cited_subjects(body):
    """Every backtick-quoted string in the Resolution — the candidate commit subjects.

    The convention is to cite the resolving commit's SUBJECT in backticks
    (`feat(ui): ... (UI-1)`); a Resolution also backticks file paths and flags,
    so this returns all of them and the caller matches against real subjects.
    """
    sec = resolution_section(body) or ""
    return [m.group(1).strip() for m in BACKTICKED_RE.finditer(sec)]


def head_subjects():
    """{subject: (full hash, abbreviated hash)} for every commit reachable from HEAD,
    newest wins on a duplicate subject. None if git can't answer."""
    try:
        proc = subprocess.run(["git", "log", "--format=%H%x00%h%x00%s", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = {}
    for line in proc.stdout.splitlines():
        parts = line.split("\0", 2)
        if len(parts) != 3:
            continue
        full, short, subject = parts
        out.setdefault(subject, (full, short))   # first seen = newest
    return out


def dirty_backlog_paths():
    """Repo-relative paths under the backlog dir that differ from HEAD (staged,
    unstaged or untracked), as POSIX strings. None if git can't answer."""
    try:
        proc = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all",
                               "--", BACKLOG_REL], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        out.add(path.strip().strip('"'))
    return out


def resolving_commit(issue, subjects):
    """(full, short) of the HEAD commit whose subject the issue's Resolution cites, or None."""
    body = (ROOT / issue["_path"]).read_text(encoding="utf-8")
    for cand in cited_subjects(body):
        if cand in subjects:
            return subjects[cand]
    return None


def unresolvable_verified(issues, subjects=None, dirty=None):
    """`status: verified` issues that cannot be closed by --backfill.

    Two rules. A verified issue must carry a filled Resolution (not the stub),
    and that Resolution must cite, in backticks, a commit subject found EXACTLY
    on HEAD — a lane that marked verified but whose Resolution names a subject
    that drifted from the actual commit, or an issue whose resolving commit is
    not on this clone, both surface here after the pull.

    The one exception: an issue file that is DIRTY in the working tree skips
    the subject rule. In a worktree lane the close rides in the resolving
    commit, so at the commit gate (pytest before `git commit`) that commit does
    not exist yet and its subject cannot be on HEAD. Once committed the file is
    clean and the rule applies in full — which is what `--check` sees right
    before the push, and what startup sees after the pull.

    `subjects` and `dirty` are injectable for tests; None means ask git, and
    if git can't answer the subject rule is skipped (the Resolution rule is
    not — it needs no git).
    """
    out = []
    verified = [it for it in issues if it.get("status") == "verified"]
    if not verified:
        return out
    if subjects is None:
        subjects = head_subjects()
    if dirty is None:
        dirty = dirty_backlog_paths()
    for it in verified:
        path = it["_path"]
        body = (ROOT / path).read_text(encoding="utf-8")
        if not resolution_is_filled(body):
            out.append(f"{path}: status=verified but the Resolution is empty or still the stub — "
                       "fill it, citing the resolving commit SUBJECT in backticks")
            continue
        if subjects is None:
            continue
        if dirty is not None and Path(path).as_posix() in dirty:
            continue   # uncommitted close: the resolving commit is the one about to be made
        if resolving_commit(it, subjects) is None:
            cited = cited_subjects(body)
            out.append(f"{path}: status=verified but no backticked string in its Resolution is a "
                       f"commit subject on HEAD (checked {len(cited)}) — the subject drifted from "
                       "the actual commit, or the resolving commit is not on this clone yet")
    return out


# --- the resolution field (ADMIN-10) -------------------------------------

def _resolution_required(closed_date):
    """Does a closed issue with this `closed:` date need a `resolution:`?

    RESOLUTION_CUTOVER None (the default) means always. A project that adopted the
    field mid-history sets `backlog.resolution_required_from`; issues closed
    before it are left alone. An undated close is left alone in both modes.
    """
    if not closed_date:
        return False
    if RESOLUTION_CUTOVER is None:
        return True
    return closed_date >= RESOLUTION_CUTOVER


def resolution_problems(issues):
    """`resolution:` values that disagree with the issue's status or commit.

    A live issue carries none; a `verified` issue always carries one (it is the
    closing lane's statement, and the backfill never invents it); a `closed`
    issue carries one from RESOLUTION_CUTOVER on; and `wont-do` cites no commit
    (no change, no hash). Issues closed before the cutover are left alone.
    """
    out = []
    for it in issues:
        path, status, res = it["_path"], it.get("status"), it.get("resolution")
        if status in LIVE_STATUSES and res is not None:
            out.append(f"{path}: resolution={res!r} on a {status} issue — only a verified or "
                       "closed issue carries one; set it when the issue closes")
        elif status == "verified" and res is None:
            out.append(f"{path}: status=verified but resolution is null — set one of "
                       f"{' | '.join(RESOLUTIONS)}")
        elif status == "closed" and res is None and _resolution_required(it.get("closed")):
            since = f" (required from {RESOLUTION_CUTOVER})" if RESOLUTION_CUTOVER else ""
            out.append(f"{path}: closed {it.get('closed')} without a resolution — set one of "
                       f"{' | '.join(RESOLUTIONS)}{since}")
        if res == "wont-do" and it.get("commit"):
            out.append(f"{path}: resolution=wont-do but commit={it.get('commit')!r} — an issue "
                       "closed without a change cites no commit; set commit: null or resolution: done")
    return out


# --- epic parents (INFRA-52) ---------------------------------------------

def dangling_epics(issues):
    """`epic:` fields that do not name an existing epic-typed issue.

    A child that names a parent which does not exist, or which is not an
    epic, or which is itself, would render under a facet chip nobody can
    resolve. Cheap to check at every gate, and the frontmatter is the only
    place the relation lives — the epic's own `links:` list is prose-adjacent
    and not read for this.
    """
    by_id = {it.get("id"): it for it in issues}
    out = []
    for it in issues:
        parent = it.get("epic")
        if not parent:
            continue
        if parent == it.get("id"):
            out.append(f"{it['_path']}: epic={parent!r} names itself")
        elif parent not in by_id:
            out.append(f"{it['_path']}: epic={parent!r} names an issue that does not exist")
        elif by_id[parent].get("type") != "epic":
            out.append(f"{it['_path']}: epic={parent!r} names a {by_id[parent].get('type')!r}, "
                       "not an epic — set the parent's `type: epic` or drop the field")
    return out


def epic_children(issues, epic_id):
    """Issues whose `epic:` names `epic_id`, in view order."""
    return sorted((it for it in issues if it.get("epic") == epic_id), key=sort_key)


def epic_rollup(issues, epic_id):
    """{status: count} over the epic's children, only the statuses present."""
    counts = {}
    for it in epic_children(issues, epic_id):
        s = it.get("status") or "?"
        counts[s] = counts.get(s, 0) + 1
    return {s: counts[s] for s in STATUSES if s in counts} | {
        s: n for s, n in counts.items() if s not in STATUSES}


# --- the doc loop (INFRA-41) ---------------------------------------------

DOCS_LINE_RE = re.compile(r"^[ \t]*(?:[-*][ \t]+)?(?:\*\*)?Docs:", re.M)


def is_docs_lane(path):
    """True for a path no living doc describes -- the `Docs:`-line gate's exemption.

    Read from DOCS_LANE_PREFIXES (`backlog.docs_lane_prefixes`, defaulting to
    `git.main_direct_paths`). Each entry is one of: a directory prefix ending in
    `/` (`docs/`), a root-level glob containing `*` (`*.md`, matched against
    top-level files only), or an exact repo-relative path. Everything else --
    source, tests, CI, skills, root config -- is a change that may have just made
    a doc paragraph untrue. Keep the list short on purpose.
    """
    import fnmatch
    p = str(path).replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    for entry in DOCS_LANE_PREFIXES:
        e = str(entry).replace("\\", "/")
        if e.startswith("./"):
            e = e[2:]
        if e.endswith("/"):
            if p.startswith(e):
                return True
        elif "*" in e:
            if "/" not in p and fnmatch.fnmatch(p, e):
                return True
        elif p == e:
            return True
    return False


def commit_paths(full_hash):
    """Repo-relative paths a commit touched, or None if git can't answer.

    NUL-separated (`-z`): session-asset names carry spaces, apostrophes and
    em dashes, and without `-z` git C-quotes any non-ASCII path, so a
    line-and-strip parse returns a name no other path compares equal to.
    """
    try:
        proc = subprocess.run(["git", "show", "--format=", "--name-only", "-z", full_hash], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return {p for p in proc.stdout.split("\0") if p.strip()}


def dirty_paths():
    """Every path in the working tree that differs from HEAD (staged, unstaged,
    untracked), whole repo, or None if git can't answer. For a verified issue
    that is itself dirty, this IS the change about to be committed with it."""
    try:
        proc = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    # -z: `XY path\0` per entry, unquoted; a rename/copy entry is followed by a
    # second NUL-terminated chunk carrying the ORIGINAL path, which is skipped.
    out, chunks = set(), proc.stdout.split("\0")
    i = 0
    while i < len(chunks):
        entry = chunks[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        out.add(path)
        if "R" in xy or "C" in xy:
            i += 1
    return out


def has_docs_line(body):
    """A `Docs:` line inside the Resolution section — bare, bolded or bulleted."""
    return bool(DOCS_LINE_RE.search(resolution_section(body) or ""))


def undocumented_verified(issues, subjects=None, dirty=None, touched=None):
    """`status: verified` issues whose change reached outside the docs lane but
    whose Resolution carries no `Docs:` line.

    The doc loop (INFRA-15) lives in `worktree-increment` step 8a: after
    verification the lane names the docs its diff touched, edits the paragraph
    or queues a DOC issue, and records the outcome as a `Docs:` line — "nothing"
    included, so silence is distinguishable from not having looked. Until
    INFRA-41 the only check was `session-closeout` step 3, which the operator's worktree
    sessions never run; six code lanes shipped without the line in two weeks.

    Where the change is read from: a verified issue that is DIRTY in the
    working tree is being closed in the commit about to be made, so its change
    is the dirty tree itself; a clean one is read from the resolving commit its
    Resolution cites (found by subject, as --backfill does). No resolving
    commit on HEAD is unresolvable_verified()'s finding, not this one. `touched`
    (callable: issue -> set of paths or None), `subjects` and `dirty` are
    injectable for tests; None means ask git, and if git can't answer the
    issue is skipped rather than flagged.
    """
    out = []
    verified = [it for it in issues if it.get("status") == "verified"]
    if not verified:
        return out
    if subjects is None:
        subjects = head_subjects()
    if dirty is None:
        dirty = dirty_backlog_paths()

    def default_touched(it):
        if dirty is not None and Path(it["_path"]).as_posix() in dirty:
            return dirty_paths()
        if subjects is None:
            return None
        hit = resolving_commit(it, subjects)
        return commit_paths(hit[0]) if hit else None

    touched = touched or default_touched
    for it in verified:
        path = it["_path"]
        body = (ROOT / path).read_text(encoding="utf-8")
        if has_docs_line(body):
            continue
        paths = touched(it)
        if not paths:
            continue
        code = sorted(p for p in paths if not is_docs_lane(p))
        if not code:
            continue
        shown = ", ".join(code[:3]) + (f" (+{len(code) - 3} more)" if len(code) > 3 else "")
        out.append(f"{path}: status=verified and its change touched {shown} but the Resolution "
                   "has no `Docs:` line — name the doc edited or the DOC issue queued, or write "
                   "`Docs: nothing — this increment changed no documented behavior` "
                   "(worktree-increment step 8a, INFRA-41)")
    return out


def check_problems(issues, problems):
    """Everything --check and the test suite assert, as one list of strings."""
    return (list(problems) + orphaned_claims(issues) + orphaned_commit_citations(issues)
            + unresolvable_verified(issues) + undocumented_verified(issues)
            + dangling_epics(issues) + resolution_problems(issues))


# --- the backfill (ADMIN-8) ---------------------------------------------

BACKFILL_SUBJECT = "docs(backlog): close {ids} — backfill resolving commit hash"


def git_user_name():
    return lc.git_user_name(cwd=ROOT)


def machine():
    """This machine's operators[] row (or the synthesized solo / unknown row)."""
    return MACHINE


def machine_id():
    """`<operators[].id>` for a known (user.name, platform) pair, else `<user>+<platform>`."""
    return MACHINE["id"]


def certifies():
    """May this machine run --backfill? Solo mode: always. Otherwise the row says."""
    return bool(MACHINE.get("certifies"))


def _rewrite_frontmatter(text, updates):
    """Return `text` with the given frontmatter keys replaced in place, byte-for-byte
    elsewhere. Keys absent from the frontmatter are left absent (never appended)."""
    lines = text.split("\n")
    assert lines and lines[0].strip() == "---"
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            break
        key, sep, _ = lines[i].partition(":")
        if sep and key.strip() in updates:
            lines[i] = f"{key.strip()}: {updates[key.strip()]}"
    return "\n".join(lines)


def backfill_verified(issues, subjects=None, today=None, dry_run=False):
    """Close every `verified` issue whose cited subject is on HEAD.

    For each: `commit:` <- the resolving commit's abbreviated hash, `status:` <-
    closed, `closed:` <- today if it was null (a lane that dated it keeps its
    date). Nothing else in the file changes. Verified issues with no resolvable
    subject are left alone and returned as `skipped` (they are what --check
    flags), and so is one whose resolving commit reached outside the docs lane
    without a `Docs:` line in the Resolution (INFRA-41) — the backfill runs at
    startup BEFORE the check does, and a closed issue is never checked again,
    so closing it here would be the one path around the doc-loop gate.
    Returns (closed, skipped): lists of (issue, detail).
    """
    if subjects is None:
        subjects = head_subjects()
    today = today or datetime.date.today().isoformat()
    closed, skipped = [], []
    for it in issues:
        if it.get("status") != "verified":
            continue
        path = ROOT / it["_path"]
        body = path.read_text(encoding="utf-8")
        if not resolution_is_filled(body):
            skipped.append((it, "Resolution empty or stub"))
            continue
        if it.get("resolution") is None:
            skipped.append((it, "resolution: null — the closing lane sets it, the backfill never guesses"))
            continue
        if it.get("resolution") == "wont-do":
            skipped.append((it, "resolution: wont-do on a verified issue — verified means a change "
                                "landed; a won't-do closes directly with commit: null"))
            continue
        hit = resolving_commit(it, subjects) if subjects else None
        if hit is None:
            skipped.append((it, "cited subject not on HEAD"))
            continue
        full, short = hit
        if not has_docs_line(body):
            paths = commit_paths(full)
            code = sorted(p for p in (paths or ()) if not is_docs_lane(p))
            if code:
                skipped.append((it, f"no `Docs:` line in the Resolution but the commit touched "
                                    f"{code[0]}" + (f" (+{len(code) - 1} more)" if len(code) > 1 else "")
                                    + " — worktree-increment 8a, INFRA-41"))
                continue
        updates = {"status": "closed", "commit": short}
        if not it.get("closed"):
            updates["closed"] = today
        if not dry_run:
            path.write_text(_rewrite_frontmatter(body, updates), encoding="utf-8")
        closed.append((it, short))
    return closed, skipped


def commit_backfill(closed):
    """Stage the closed issue files BY EXPLICIT PATH and commit them. No push."""
    paths = [str(it["_path"]) for it, _ in closed]
    ids = ", ".join(it["id"] for it, _ in closed)
    subprocess.run(["git", "add", "--", *paths], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-q", "-m", BACKFILL_SUBJECT.format(ids=ids)],
                   cwd=ROOT, check=True)
    return BACKFILL_SUBJECT.format(ids=ids)


def _cell(v):
    return (v if v not in (None, "", []) else "—")


def render_index(issues):
    open_issues = [i for i in issues if i.get("status") in LIVE_STATUSES]
    verified = [i for i in issues if i.get("status") == "verified"]
    closed = [i for i in issues if i.get("status") == "closed"]
    lines = [
        "# Backlog index",
        "",
        "**GENERATED by the lanes plugin's `backlog_index.py` — local, gitignored, never hand-edit.**",
        "Regenerate after `git pull` or any issue change (session startup does it for",
        "you). One row per issue; the issue file is the source of truth. Ages are",
        "computed by `--report`, not stored here.",
        "",
    ]
    by_proj = {}
    for i in open_issues:
        by_proj.setdefault(i.get("project"), []).append(i)
    counts = " · ".join(f"{p} {len(by_proj[p])}" for p in PROJECTS if p in by_proj)
    lines.append(f"**{len(open_issues)} live** ({counts}) · {len(verified)} verified "
                 f"(landed, awaiting close) · {len(closed)} closed")
    lines += [
        "",
        "## Open / blocked / paused",
        "",
        "| ID | Type | Status | Pri | Assignee | Opened | Epic | Blocked on | Title |",
        "| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |",
    ]
    for i in sorted(open_issues, key=sort_key):
        title = i["_title"]
        title = title if len(title) <= 90 else title[:89] + "…"
        lines.append(
            f"| [{i['id']}]({i['_path'].as_posix().replace(BACKLOG_REL + '/', '')}) "
            f"| {_cell(i.get('type'))} | {_cell(i.get('status'))} | {_cell(i.get('priority'))} "
            f"| {_cell(i.get('assignee'))} | {_cell(i.get('opened'))} | {_cell(i.get('epic'))} "
            f"| {_cell(i.get('blocked_on'))} | {title} |")
    lines += ["", "## Verified — landed, awaiting close", ""]
    if verified:
        lines += [f"Resolving commit is on origin; {CERTIFIER_LABEL} next startup fills `commit:` and closes "
                  "(`backlog_index.py --backfill`).", "",
                  "| ID | Type | Assignee | Opened | Title |", "| :-- | :-- | :-- | :-- | :-- |"]
        for i in sorted(verified, key=sort_key):
            lines.append(f"| [{i['id']}]({i['_path'].as_posix().replace(BACKLOG_REL + '/', '')}) "
                         f"| {_cell(i.get('type'))} | {_cell(i.get('assignee'))} "
                         f"| {_cell(i.get('opened'))} | {i['_title']} |")
    else:
        lines.append("(none)")
    lines += ["", "## Closed", ""]
    if closed:
        lines += ["| ID | Closed | Type | Assignee | Resolution | Commit | Title |",
                  "| :-- | :-- | :-- | :-- | :-- | :-- | :-- |"]
        for i in sorted(closed, key=lambda x: (x.get("closed") or "", x.get("id") or ""), reverse=True):
            commit = f"`{i['commit']}`" if i.get("commit") else "—"
            lines.append(f"| [{i['id']}]({i['_path'].as_posix().replace(BACKLOG_REL + '/', '')}) "
                         f"| {_cell(i.get('closed'))} | {_cell(i.get('type'))} "
                         f"| {_cell(i.get('assignee'))} | {_cell(i.get('resolution'))} "
                         f"| {commit} | {i['_title']} |")
    else:
        lines.append("(none yet)")
    lines.append("")
    return "\n".join(lines)


def _age(datestr):
    if not datestr:
        return None
    try:
        y, m, d = map(int, datestr.split("-"))
        return (datetime.date.today() - datetime.date(y, m, d)).days
    except ValueError:
        return None


# --- the browsable HTML view (INFRA-14) ---------------------------------
#
# Same data as INDEX.md, same regeneration, but sortable and filterable, which
# the Markdown table and the --report terminal view structurally cannot be.
# Self-contained: inlined CSS + vanilla JS, no dependency and no build step, so
# it stays stdlib-only and runs on both operators' machines exactly as the rest
# of this script does. Gitignored beside INDEX.md for the ADMIN-6 reason.

# (label, dataset key to sort on, numeric?) — one list per section, because the
# closed rows answer different questions (when/what commit) than the live ones.
OPEN_COLS = (("ID", "id", 0), ("Pri", "priorityRank", 1), ("Status", "statusRank", 1),
             ("Type", "type", 0), ("Assignee", "assignee", 0), ("Opened", "opened", 0),
             ("Age", "age", 1), ("Epic", "epic", 0), ("Blocked on", "blocked", 0),
             ("Title", "title", 0))
CLOSED_COLS = (("ID", "id", 0), ("Pri", "priorityRank", 1), ("Type", "type", 0),
               ("Assignee", "assignee", 0), ("Opened", "opened", 0), ("Closed", "closed", 0),
               ("Resolution", "resolution", 0), ("Commit", "commit", 0), ("Title", "title", 0))
VERIFIED_COLS = (("ID", "id", 0), ("Pri", "priorityRank", 1), ("Type", "type", 0),
                 ("Assignee", "assignee", 0), ("Opened", "opened", 0), ("Age", "age", 1),
                 ("Title", "title", 0))

HTML_STYLE = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1c1c1e;--mut:#6b7280;--line:#e5e7eb;
      --zebra:#fafafa;--hov:#f3f4f6;--chip:#f3f4f6;--accent:#2563eb}
@media (prefers-color-scheme:dark){:root{--bg:#16181d;--fg:#e5e7eb;--mut:#9aa0a6;
      --line:#2a2e36;--zebra:#1a1d23;--hov:#232830;--chip:#232830;--accent:#7aa2f7}}
*{box-sizing:border-box}
body{margin:0;padding:1.1rem 1.4rem 5rem;background:var(--bg);color:var(--fg);
     font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
h1{font-size:1.1rem;margin:0 0 .1rem}
.sub{color:var(--mut);margin:0;font-size:11.5px;max-width:70ch}
.counts{margin:.55rem 0 .9rem;font-size:12px;color:var(--mut)}
.counts b{color:var(--fg)}
.controls{border:1px solid var(--line);border-radius:7px;padding:.6rem .7rem;margin-bottom:1rem}
#q{width:100%;max-width:34rem;padding:.42rem .6rem;font:inherit;color:var(--fg);
   background:var(--bg);border:1px solid var(--line);border-radius:5px}
#q:focus{outline:2px solid var(--accent);outline-offset:-1px}
.facets{margin:.6rem 0 .1rem}
fieldset{border:0;margin:0 0 .3rem;padding:0;display:flex;flex-wrap:wrap;align-items:baseline;
         gap:.3rem}
fieldset:last-child{margin-bottom:0}
.flabel{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.04em;
        flex:0 0 4.6rem;padding-top:.1rem}
.allbtn{flex:0 0 auto;font-size:10.5px;padding:.1rem .5rem .13rem;border-radius:20px;
        border:1px dashed var(--line);background:transparent;color:var(--mut);cursor:pointer}
.allbtn:hover{color:var(--fg);border-style:solid;background:var(--chip)}
label.chip{display:inline-flex;align-items:center;gap:.25rem;background:var(--chip);
           border:1px solid transparent;border-radius:20px;padding:.1rem .5rem .13rem .35rem;
           cursor:pointer;user-select:none;font-size:11.5px}
label.chip:hover{border-color:var(--line)}
label.chip input{margin:0;accent-color:var(--accent)}
label.chip.off{opacity:.42}
.rowbtns{margin-top:.55rem;display:flex;gap:.5rem;align-items:center}
button{font:inherit;font-size:11.5px;padding:.22rem .6rem;border-radius:5px;cursor:pointer;
       border:1px solid var(--line);background:var(--chip);color:var(--fg)}
button:hover{background:var(--hov)}
#showing{color:var(--mut);font-size:11.5px;margin:0}
details.sec{margin-bottom:1.1rem}
details.sec>summary{cursor:pointer;font-weight:600;padding:.3rem 0;font-size:12.5px}
details.sec>summary::marker{color:var(--mut)}
table{border-collapse:collapse;width:100%;margin-top:.35rem}
th,td{text-align:left;padding:.3rem .55rem;border-bottom:1px solid var(--line);
      vertical-align:top}
thead th{position:sticky;top:0;background:var(--bg);cursor:pointer;white-space:nowrap;
         font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);
         border-bottom:1.5px solid var(--line);user-select:none}
thead th:hover{color:var(--fg)}
thead th::after{content:"";opacity:.45;font-size:9px}
thead th.asc::after{content:" \\25B2"}
thead th.desc::after{content:" \\25BC"}
tbody tr:nth-child(even of :not([hidden])){background:var(--zebra)}
tbody tr:hover{background:var(--hov)}
td.id a{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;
        color:var(--accent);text-decoration:none;white-space:nowrap}
td.id a:hover{text-decoration:underline}
td.title{width:44%}
td.blocked{color:var(--mut);max-width:24ch}
td.num,td.date{white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--mut)}
td.commit{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--mut)}
.pill{display:inline-block;border-radius:20px;padding:.03rem .45rem .07rem;font-size:10.5px;
      white-space:nowrap;background:var(--chip);color:var(--mut)}
.p-critical{background:#fee2e2;color:#991b1b}
.p-high{background:#ffedd5;color:#9a3412}
.s-in-progress{background:#dbeafe;color:#1e40af}
.s-blocked{background:#fef3c7;color:#92400e}
.s-paused{background:#ede9fe;color:#5b21b6}
.s-verified{background:#dcfce7;color:#166534}
@media (prefers-color-scheme:dark){
  .p-critical{background:#4c1d1d;color:#fca5a5}
  .p-high{background:#4a2c11;color:#fdba74}
  .s-in-progress{background:#1b2f52;color:#93c5fd}
  .s-blocked{background:#43330f;color:#fcd34d}
  .s-paused{background:#2f2352;color:#c4b5fd}
  .s-verified{background:#14352a;color:#86efac}}
.empty{color:var(--mut);padding:.5rem .55rem}
"""

HTML_SCRIPT = """
const norm = s => (s || '').toLowerCase();
const tables = () => Array.from(document.querySelectorAll('table.issues'));
const bodyRows = t => Array.from(t.tBodies[0].rows);

function checked(field){
  const boxes = document.querySelectorAll('fieldset[data-field="' + field + '"] input');
  const on = new Set();
  boxes.forEach(b => { b.parentElement.classList.toggle('off', !b.checked);
                       if (b.checked) on.add(b.value); });
  const btn = document.querySelector('.allbtn[data-all="' + field + '"]');
  if (btn) btn.textContent = on.size === boxes.length ? 'none' : 'all';
  return on;
}

function applyFilter(){
  const q = norm(document.getElementById('q').value).trim();
  const f = {project: checked('project'), status: checked('status'),
             priority: checked('priority'), assignee: checked('assignee'),
             epic: checked('epic')};
  let shown = 0, total = 0;
  tables().forEach(t => {
    let n = 0;
    bodyRows(t).forEach(r => {
      total++;
      const d = r.dataset;
      // An epic row lists itself AND its parent, a child lists its parent, so
      // one chip shows the whole family (INFRA-52).
      const ok = f.project.has(d.project) && f.status.has(d.status)
              && f.priority.has(d.priority) && f.assignee.has(d.assignee)
              && d.epics.split(' ').some(e => f.epic.has(e))
              && (!q || d.haystack.includes(q));
      r.hidden = !ok;
      if (ok) { n++; shown++; }
    });
    t.closest('details').querySelector('.n').textContent = n;
  });
  document.getElementById('showing').textContent =
    'showing ' + shown + ' of ' + total + ' issues';
}

function sortBy(th){
  const t = th.closest('table'), key = th.dataset.key, num = th.dataset.num === '1';
  const asc = !th.classList.contains('asc');
  t.querySelectorAll('thead th').forEach(h => h.classList.remove('asc', 'desc'));
  th.classList.add(asc ? 'asc' : 'desc');
  const body = t.tBodies[0];
  bodyRows(t).sort((a, b) => {
    let x = a.dataset[key], y = b.dataset[key];
    if (num) { x = Number(x); y = Number(y); }
    return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1);
  }).forEach(r => body.appendChild(r));
}

document.querySelectorAll('thead th').forEach(th =>
  th.addEventListener('click', () => sortBy(th)));
document.getElementById('q').addEventListener('input', applyFilter);
document.querySelectorAll('.facets input').forEach(b =>
  b.addEventListener('change', applyFilter));
document.querySelectorAll('.allbtn').forEach(btn =>
  btn.addEventListener('click', () => {
    const boxes = btn.closest('fieldset').querySelectorAll('input');
    // All on -> clear the row; anything off -> select the whole row back.
    const want = Array.from(boxes).some(b => !b.checked);
    boxes.forEach(b => { b.checked = want; });
    applyFilter();
  }));
document.getElementById('reset').addEventListener('click', () => {
  document.getElementById('q').value = '';
  document.querySelectorAll('.facets input').forEach(b => { b.checked = true; });
  applyFilter();
});
document.getElementById('q').addEventListener('keydown', e => {
  if (e.key === 'Escape') { e.target.value = ''; applyFilter(); }
});
applyFilter();
"""


def _esc(v):
    return html.escape("" if v is None else str(v))


def _pill(kind, value):
    if not value:
        return '<span class="pill">—</span>'
    return f'<span class="pill {kind}-{_esc(value)}">{_esc(value)}</span>'


def _facet(field, values):
    chips = "".join(
        f'<label class="chip"><input type="checkbox" value="{_esc(v)}" checked>{_esc(v)}</label>'
        for v in values)
    return (f'<fieldset data-field="{field}"><span class="flabel">{field}</span>'
            f'<button type="button" class="allbtn" data-all="{field}">none</button>{chips}</fieldset>')


def _html_row(i, cols):
    href = i["_path"].as_posix().replace(BACKLOG_REL + "/", "")
    title = i["_title"]
    age = i.get("_age")
    haystack = norm_join(i)
    attrs = {
        "project": i.get("project") or "", "type": i.get("type") or "",
        "status": i.get("status") or "", "priority": i.get("priority") or "",
        "assignee": i.get("assignee") or "—",
        "resolution": i.get("resolution") or "",
        "id": _sort_id(i), "opened": i.get("opened") or "", "closed": i.get("closed") or "",
        "commit": i.get("commit") or "", "blocked": (i.get("blocked_on") or "").lower(),
        "title": i["_title"].lower(),
        "epic": _sort_id({"id": i.get("epic")}) if i.get("epic") else "~",
        "epics": _epic_family(i),
        "age": str(age if age is not None else -1),
        "priority-rank": str(PRIORITY_RANK.get(i.get("priority"), 9)),
        "status-rank": str(STATUS_RANK.get(i.get("status"), 9)),
        "haystack": haystack,
    }
    cells = {
        "id": f'<td class="id"><a href="{_esc(href)}">{_esc(i["id"])}</a></td>',
        "priorityRank": f'<td>{_pill("p", i.get("priority"))}</td>',
        "statusRank": f'<td>{_pill("s", i.get("status"))}</td>',
        "type": f'<td>{_esc(i.get("type"))}</td>',
        "assignee": f'<td>{_esc(i.get("assignee") or "—")}</td>',
        "opened": f'<td class="date">{_esc(i.get("opened") or "—")}</td>',
        "closed": f'<td class="date">{_esc(i.get("closed") or "—")}</td>',
        "commit": f'<td class="commit">{_esc(i.get("commit") or "—")}</td>',
        "resolution": f'<td>{_esc(i.get("resolution") or "—")}</td>',
        "age": f'<td class="num">{age}d</td>' if age is not None else '<td class="num">—</td>',
        "blocked": f'<td class="blocked">{_esc(i.get("blocked_on") or "")}</td>',
        "epic": f'<td class="id">{_esc(i.get("epic") or "—")}</td>',
        "title": f'<td class="title">{_esc(title)}</td>',
    }
    attr_str = " ".join(f'data-{k}="{_esc(v)}"' for k, v in attrs.items())
    return f"<tr {attr_str}>" + "".join(cells[key] for _, key, _n in cols) + "</tr>"


def norm_join(i):
    """Everything the free-text box searches, lowercased into one string."""
    return (" ".join(str(x) for x in (
        i.get("id"), i["_title"], i.get("assignee") or "", i.get("reported_by") or "",
        i.get("resolution") or "", i.get("type") or "",
        i.get("blocked_on") or "", i.get("epic") or "",
        " ".join(i.get("links") or [])) if x)).lower()


def _epic_family(i):
    """The facet values a row answers to: its parent epic, plus itself if it IS
    an epic. "—" for a row under no epic, so the no-epic chip has something to
    match. Space-separated for the JS split."""
    fam = []
    if i.get("type") == "epic" and i.get("id"):
        fam.append(i["id"])
    if i.get("epic"):
        fam.append(i["epic"])
    return " ".join(fam) if fam else "—"


def _sort_id(i):
    """`INFRA-9` must sort before `INFRA-14`, so zero-pad the numeric half."""
    iid = i.get("id") or ""
    proj, _, num = iid.partition("-")
    return f"{proj}-{int(num):04d}" if num.isdigit() else iid


def _html_table(issues, cols, empty):
    if not issues:
        return f'<p class="empty">{empty}</p>'
    head = "".join(f'<th data-key="{key}" data-num="{num}">{_esc(label)}</th>'
                   for label, key, num in cols)
    rows = "\n".join(_html_row(i, cols) for i in issues)
    return f'<table class="issues"><thead><tr>{head}</tr></thead><tbody>\n{rows}\n</tbody></table>'


def html_sort_key(it):
    """The view's default order: priority, then status, then oldest-first.

    Deliberately NOT --report's age-only sort — that was the complaint INFRA-14
    came from ("sorted by days open doesn't always make sense"). Every column is
    one click away regardless.
    """
    return (PRIORITY_RANK.get(it.get("priority"), 9),
            STATUS_RANK.get(it.get("status"), 9),
            -(it.get("_age") if it.get("_age") is not None else -1),
            it.get("id") or "")


def render_html(issues):
    for i in issues:
        i["_age"] = _age(i.get("opened"))
    open_issues = sorted((i for i in issues if i.get("status") in LIVE_STATUSES), key=html_sort_key)
    verified = sorted((i for i in issues if i.get("status") == "verified"), key=html_sort_key)
    closed = sorted((i for i in issues if i.get("status") == "closed"),
                    key=lambda x: (x.get("closed") or "", x.get("id") or ""), reverse=True)

    present = lambda field, vocab: [v for v in vocab if any(i.get(field) == v for i in issues)]
    assignees = sorted({i.get("assignee") or "—" for i in issues})
    epics = sorted({i["id"] for i in issues if i.get("type") == "epic" and i.get("id")}
                   | {i["epic"] for i in issues if i.get("epic")},
                   key=lambda e: _sort_id({"id": e}))
    facets = "".join((
        _facet("project", present("project", PROJECTS)),
        _facet("status", present("status", STATUSES)),
        _facet("priority", present("priority", PRIORITIES)),
        _facet("assignee", assignees),
        _facet("epic", epics + ["—"]) if epics else "",
    ))

    by_proj = {}
    for i in open_issues:
        by_proj.setdefault(i.get("project"), []).append(i)
    counts = " · ".join(f"{p} {len(by_proj[p])}" for p in PROJECTS if p in by_proj)
    warn = ""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backlog — {_esc(REPO_NAME)}</title>
<style>{HTML_STYLE}</style>
</head>
<body>
<h1>Backlog</h1>
<p class="sub">GENERATED by the lanes plugin's <code>backlog_index.py</code> — local, gitignored, never
hand-edit. The issue files under <code>{_esc(BACKLOG_REL)}/&lt;PROJECT&gt;/</code> are the source of
truth; click an ID to open one. Regenerated {stamp}.</p>
<p class="counts"><b>{len(open_issues)}</b> live ({_esc(counts)}) · <b>{len(verified)}</b> verified
(landed, awaiting close) · <b>{len(closed)}</b> closed</p>
{warn}
<div class="controls">
  <input id="q" type="search" placeholder="Filter — id, title, assignee, reporter, resolution, type, blocked-on, links…"
         autocomplete="off" spellcheck="false">
  <div class="facets">{facets}</div>
  <div class="rowbtns"><button id="reset" type="button">Reset filters</button>
    <p id="showing"></p></div>
</div>
<details class="sec" open>
  <summary>Open / in-progress / blocked / paused (<span class="n">{len(open_issues)}</span>)</summary>
  {_html_table(open_issues, OPEN_COLS, "No live issues match.")}
</details>
<details class="sec" {"open" if verified else ""}>
  <summary>Verified — landed, awaiting {html.escape(CERTIFIER_LABEL, quote=False)} close (<span class="n">{len(verified)}</span>)</summary>
  {_html_table(verified, VERIFIED_COLS, "Nothing awaiting close.")}
</details>
<details class="sec">
  <summary>Closed (<span class="n">{len(closed)}</span>)</summary>
  {_html_table(closed, CLOSED_COLS, "No closed issues yet.")}
</details>
<script>{HTML_SCRIPT}</script>
</body>
</html>
"""


def render_report(issues, who):
    open_issues = [i for i in issues if i.get("status") in LIVE_STATUSES]
    verified = [i for i in issues if i.get("status") == "verified"]
    if who != "both":
        mine = [i for i in open_issues if i.get("assignee") in (who, "shared")]
        # The other operator's issues stuck on THIS operator — what my work unblocks.
        waiting = [i for i in open_issues if i.get("assignee") not in (who, "shared", None)
                   and who in (i.get("blocked_on") or "").lower()]
    else:
        mine, waiting = open_issues, []
    print(f"{'='*100}\nBACKLOG ({who}) — {len(mine)} live\n{'='*100}")
    for i in sorted(mine, key=lambda x: (x["_age"] is None, -(x["_age"] or 0))):
        age = f"{i['_age']}d" if i["_age"] is not None else "undated"
        blocked = f"  ⛔ {i['blocked_on']}" if i.get("blocked_on") else ""
        print(f"{i['id']:>10} {i.get('type') or '?':>8} {i.get('status') or '?':>11} "
              f"{i.get('priority') or '?':>8} [{age:>7}] {i['_title'][:80]}{blocked}")
    sc = {s: sum(1 for i in mine if i.get("status") == s) for s in STATUSES}
    pc = {p: sum(1 for i in mine if i.get("priority") == p and i.get("status") != "closed") for p in PRIORITIES}
    ages = [i["_age"] for i in mine if i["_age"] is not None
            and i.get("status") in ("open", "in-progress")]
    print(f"\n  status: " + " · ".join(f"{s} {n}" for s, n in sc.items() if n)
          + "  |  priority: " + " · ".join(f"{p} {n}" for p, n in pc.items() if n)
          + (f"  |  oldest open {max(ages)}d" if ages else ""))
    epics = [i for i in mine if i.get("type") == "epic"]
    if epics:
        print(f"\n  Epics — child roll-up ({len(epics)}):")
        for e in sorted(epics, key=sort_key):
            roll = epic_rollup(issues, e["id"])
            summary = " · ".join(f"{s} {n}" for s, n in roll.items()) or "no children yet"
            print(f"    {e['id']:>10}  {e['_title'][:58]:<58}  {sum(roll.values()):>2} children: {summary}")
    if waiting:
        print(f"\n  Blocked on YOU — the other operator's issues your work unblocks ({len(waiting)}):")
        for i in sorted(waiting, key=sort_key):
            print(f"    {i['id']:>10}  {i['_title'][:70]}  ⛔ {i['blocked_on']}")
    if verified:
        tail = ("run `backlog_index.py --backfill` to close" if certifies()
                else f"awaiting {CERTIFIER_LABEL} close — read-only here")
        print(f"\n  Verified — landed, awaiting close ({len(verified)}; {tail}):")
        for i in sorted(verified, key=sort_key):
            print(f"    {i['id']:>10}  {i['_title'][:70]}")
    print("\nNote: read the issue file before acting on a row — titles compress, bodies decide.")


def regenerate():
    """(Re)write both local views; returns (issues, problems). Importable by the other scripts.

    Always safe: both files are gitignored, so an incomplete set of issue files
    (a worktree branched before another lane's issue existed) produces an
    incomplete LOCAL view and nothing else.
    """
    issues, problems = load_issues()
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(render_index(issues), encoding="utf-8")
    HTML_VIEW.write_text(render_html(issues), encoding="utf-8")
    return issues, problems



# --- serve (INFRA-43) ---------------------------------------------------
# The views were GENERATED ON WRITE: something had to remember to run this
# script after every backlog change, and something did not. `session-startup`
# step 8b claims a slice, runs `--check`, commits and pushes -- and never
# regenerated, so a claim reached origin/main while the two local views still
# showed the pre-claim state. `worktree-increment` step 1.3 did say to
# regenerate, but by then the session is in a worktree and ROOT comes from
# `__file__`, so it rewrote the WORKTREE's index.html -- not the file the operator's
# bookmark points at.
#
# A full regeneration takes ~0.13s over 376 issues, so there is no reason for
# the view to be a snapshot at all. Serve it instead: re-parse on every
# request, and refreshing the URL IS the regeneration. No step can forget it.


def _reserved_port():
    """The view's port: `backlog.view_port` in the config (default 8099)."""
    return VIEW_PORT


def clone_position():
    """How far behind `origin/<main branch>` this clone is, WITHOUT fetching.

    The served view renders this clone's working tree, so a lane that just
    landed from a worktree is invisible here until the clone pulls. Saying so
    in one line beats the alternatives: fetching per request puts the network
    in a page load, and pulling on the operator's behalf would write to a
    checkout another session may be working in -- the 2026-09-10 shape.
    """
    def git(*args):
        return subprocess.run(["git", "-C", str(ROOT), *args],
                              capture_output=True, text=True, check=True).stdout.strip()
    try:
        head = git("rev-parse", "--short", "HEAD")
        behind = git("rev-list", "--count", f"HEAD..origin/{MAIN_BRANCH}")
        return head, int(behind)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return None, 0


def _banner(head, behind):
    if head is None:
        return ""
    if behind:
        return (f'<p class="sub"><strong>This clone is {behind} commit(s) behind '
                f'<code>origin/{_esc(MAIN_BRANCH)}</code></strong> (HEAD <code>{head}</code>, as of its last '
                f'fetch) — a lane that landed from a worktree will not appear until you pull.</p>')
    return (f'<p class="sub">Clone at <code>{head}</code>, level with '
            f'<code>origin/{_esc(MAIN_BRANCH)}</code> as of its last fetch. Rendered live at each request.</p>')


def serve(port=None, host="127.0.0.1"):
    """Render the HTML view fresh on every request."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    port = port or _reserved_port()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] not in ("/", "/index.html"):
                self.send_error(404, "the backlog view lives at /")
                return
            issues, problems = load_issues()
            body = render_html(issues)
            head, behind = clone_position()
            banner = _banner(head, behind)
            if banner:
                # Right under the generated-file note, which is where the eye
                # already goes for "is this current?".
                body = body.replace("</p>", "</p>\n" + banner, 1)
            if problems:
                body = body.replace("</p>", "</p>\n<p class=\"sub\">⚠️ " +
                                    html.escape("; ".join(problems)) + "</p>", 1)
            raw = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            # Never let a browser cache a view whose whole point is freshness.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass          # a request per refresh is not worth a line of output

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"backlog view → http://{host}:{port}/  (regenerates on every refresh, Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbacklog view stopped")
    finally:
        httpd.server_close()
    return 0


def main(argv=None):
    use_utf8_console()
    ap = argparse.ArgumentParser(description="lanes backlog: views, report, integrity check, backfill")
    ap.add_argument("--root", default=None,
                    help="repository to operate on (default: the one containing the cwd)")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 on structural problems, orphaned claims, orphaned commit citations, "
                         "a dangling epic: parent, a resolution: that disagrees with the "
                         "status or commit, "
                         "or a verified issue that is unresolvable or missing its Docs: line")
    ap.add_argument("--report", action="store_true", help="print aged operator view, don't write")
    ap.add_argument("--who", default=None,
                    help="an operator short name, or both (default: this machine's operator)")
    ap.add_argument("--open", action="store_true", dest="open_view",
                    help="regenerate, then open the HTML view in the default browser")
    ap.add_argument("--serve", action="store_true",
                    help="serve the view on the reserved port, regenerating on every request")
    ap.add_argument("--port", type=int, default=None,
                    help="with --serve: override the configured port (backlog.view_port)")
    ap.add_argument("--backfill", action="store_true",
                    help="certifying machine only: fill commit: on every verified issue whose cited subject is on HEAD and close it")
    ap.add_argument("--dry-run", action="store_true", help="with --backfill: report, write nothing")
    ap.add_argument("--commit", action="store_true", dest="do_commit",
                    help="with --backfill: git add the closed issue files by path and commit (never pushes)")
    args = ap.parse_args(argv)
    if args.root:
        configure(Path(args.root).resolve())

    if args.serve:
        return serve(port=args.port)

    issues, problems = load_issues()
    for p in problems:
        print(f"⚠️  {p}", file=sys.stderr)

    if args.report:
        who = args.who
        shorts = [a for a in ASSIGNEES if a != lc.SHARED_ASSIGNEE]
        if who is None:
            who = MACHINE["short"] if (SOLO or MACHINE.get("known")) else "both"
        elif who != "both" and who not in shorts:
            print(f"--who must be one of {', '.join(shorts)} or both", file=sys.stderr)
            return 2
        for i in issues:
            i["_age"] = _age(i.get("opened"))
        render_report(issues, who)
        return 1 if any("DUPLICATE" in p for p in problems) else 0

    if args.check:
        # ONE list, shared with tests/test_backlog_index.py — until ADMIN-10 the
        # CLI hand-listed the checks and silently missed the newest one.
        extra = check_problems(issues, [])
        for p in extra:
            print(f"⚠️  {p}", file=sys.stderr)
        if problems or extra:
            print(f"backlog check FAILED — {len(problems) + len(extra)} problem(s) above",
                  file=sys.stderr)
            return 1
        n_verified = sum(1 for i in issues if i.get("status") == "verified")
        print(f"backlog check OK — {len(issues)} issues, no structural problems, "
              "no orphaned claims, no orphaned commit citations, no dangling epics, "
              f"{n_verified} verified awaiting backfill (each documented).")
        return 0

    if args.backfill:
        if problems:
            print("backfill refused — fix the structural problems above first", file=sys.stderr)
            return 1
        if not certifies():
            print(f"backfill refused — this clone is {machine_id()!r} "
                  f"(git user.name {git_user_name()!r} + platform {sys.platform!r}), and its "
                  "operator row does not certify. The backfill is a backlog write that runs "
                  "on ONE machine only: two clones writing the same issue files is the race "
                  "the gate exists to prevent. Verified issues are read-only here.", file=sys.stderr)
            return 2
        closed, skipped = backfill_verified(issues, dry_run=args.dry_run)
        verb = "would close" if args.dry_run else "closed"
        for it, short in closed:
            print(f"  {verb} {it['id']:>10}  commit: {short}  {it['_path']}")
        for it, why in skipped:
            print(f"  SKIPPED {it['id']:>10}  {why}  {it['_path']}", file=sys.stderr)
        if not closed and not skipped:
            print("nothing to backfill — no verified issues.")
            return 0
        if closed and not args.dry_run:
            regenerate()
            if args.do_commit:
                subject = commit_backfill(closed)
                print(f"committed: {subject}  (not pushed)")
            else:
                paths = " ".join(str(it["_path"]) for it, _ in closed)
                print(f"not committed — stage by path: git add -- {paths}")
        return 1 if skipped else 0

    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(render_index(issues), encoding="utf-8")
    HTML_VIEW.write_text(render_html(issues), encoding="utf-8")
    print(f"wrote {INDEX.relative_to(ROOT)} + {HTML_VIEW.relative_to(ROOT)} "
          f"(local, gitignored) — {len(issues)} issues"
          + (f", {len(problems)} problem(s) above" if problems else ""))
    print(f"  sortable view → {HTML_VIEW.as_uri()}")
    if args.open_view:
        webbrowser.open(HTML_VIEW.as_uri())
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
