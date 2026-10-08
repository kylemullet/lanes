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
  python3 backlog_index.py --backfill [--dry-run] [--commit] [--push]   # certifying machines only
  python3 backlog_index.py --backfill --push --isolated   # the same, off a throwaway worktree at origin/<main>

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
on HEAD by the exact subject it cites, fills `commit:`, and flips it to `closed`. The
script refuses to backfill on a machine whose operator row does not certify; in solo
mode every machine certifies. Several certifying machines may backfill at once
(LANES-6): the close is deterministic (`closed:` is the resolving commit's committer
date, the hash a fixed 7-character abbreviation), so two machines closing the same
issue write byte-identical files, and `--push` fetches first, then converges on a
rejected push by rebasing -- identical closes merge cleanly or drop out. No machine is
named the single writer, and nothing is ever force-pushed.
"""
import argparse, datetime, html, re, shutil, subprocess, sys, tempfile, webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import lanes_config as lc              # noqa: E402
import push_guard                      # noqa: E402

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
    certifiers = list(dict.fromkeys(r["short"] for r in ops if r.get("certifies")))
    machine = cfg["machine"]
    if cfg["solo"]:
        certifier_label = "your"
    elif certifiers:
        certifier_label = f"{certifiers[0]}'s"
    else:
        certifier_label = "the certifying operator's"
    editors = list(dict.fromkeys(r["short"] for r in ops if r.get("may_edit_code", True)))
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
        "OK_FREE_PATHS": tuple(cfg["ok_free_paths"]),
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
        if meta.get("status") == "in-progress":
            meta["_marker"] = parse_marker(body)
        issues.append(meta)
    return issues, problems


# --- lanes (LANES-22 view, LANES-10 recorded identity) ----------------------
#
# A lane is a slice of one or more claimed issues: at most one ACTIVE or PENDING
# issue and the RESERVED ones queued behind it. Its identity is the frontmatter
# field `lane: <lead-ID>@<YYYY-MM-DD>`, which `lanes_claim.py` writes on every
# issue of a slice (and copies onto a `--behind` extension) and which leaves the
# issue with its claim. A claim made before the field existed is grouped from its
# marker prose instead -- under the SAME key, `<root>@<root's claim date>`, so an
# old lead and a new reservation behind it still land in one lane:
#   ⏳ IN-PROGRESS (<YYYY-MM-DD HH:MM>, <who>'s session[ on <machine>][, worktree <w>, branch <b>])
#      — **ACTIVE LANE.** | **WORKTREE PENDING.** | **RESERVED, NOT STARTED.** … queued behind <ID>
# A marker this cannot read still yields a lane of one, never a dropped issue.

MARKER_RE = re.compile(r"⏳ IN-PROGRESS \(([^)]*)\)\s*[—–-]+\s*\*\*\s*"
                       r"(ACTIVE LANE|WORKTREE PENDING|RESERVED, NOT STARTED)")
MARKER_STATES = {"ACTIVE LANE": "active", "WORKTREE PENDING": "pending",
                 "RESERVED, NOT STARTED": "reserved"}
QUEUED_RE = re.compile(r"[Qq]ueued behind\s+(?:\[\[)?([A-Z][A-Z0-9]*-\d+)")
LANE_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+@\d{4}-\d{2}-\d{2}$")


def parse_marker(body):
    """The claim marker's fields, or None when there is no readable marker."""
    for line in body.split("\n"):
        m = MARKER_RE.search(line)
        if not m:
            continue
        info, state = m.group(1), MARKER_STATES[m.group(2)]
        ts = re.match(r"\s*(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)", info)
        mach = re.search(r"session on ([^,]+)", info)
        who = re.search(r"(?:^|,\s*)([^,]+?)'s session", info)
        wt = re.search(r"worktree ([^,]+)", info)
        br = re.search(r"branch ([^,]+)", info)
        q = QUEUED_RE.search(line)
        return {"state": state,
                "claimed": ts.group(1) if ts else None,
                "who": who.group(1).strip() if who else None,
                "machine": mach.group(1).strip() if mach else None,
                "worktree": wt.group(1).strip() if wt else None,
                "branch": br.group(1).strip() if br else None,
                "behind": q.group(1) if q else None}
    return None



def lanes_in_flight(issues):
    """Group the lanes still in flight, each in slice order.

    A lane is in flight while ANY of its issues is in-progress, and until then it
    keeps the ones that already landed (`verified` / `closed` with the same `lane:`),
    so the operator sees the whole slice -- what is done and what is left -- until
    the last issue lands and the lane disappears (Kyle, 2026-10-07).

    Returns a list of {"key", "members": [issue, ...], "lead", "head", "claimed"},
    oldest claim first. `key` is the recorded `lane:` value, or the marker-derived
    one for a claim that predates the field. Members run landed-first (by close
    date), then the live ones in queued-behind order. `lead` is the slice's first
    issue (the key's ID when present), `head` the ACTIVE/PENDING one (else the
    first live one). A RESERVED issue whose lead is no longer claimed and carries
    no field stands as its own lane rather than vanishing.
    """
    claimed = {i["id"]: i for i in issues if i.get("status") == "in-progress" and i.get("id")}

    def parent(iid):
        mk = claimed[iid].get("_marker") or {}
        b = mk.get("behind")
        return b if b in claimed and b != iid else None

    def root(iid):
        path = [iid]
        while p := parent(path[-1]):
            if p in path:     # a queued-behind cycle: break it at its lowest ID
                return min(path[path.index(p):], key=_sort_id_str)
            path.append(p)
        return path[-1]

    def key(iid):
        recorded = claimed[iid].get("lane")
        if recorded:
            return str(recorded)
        r = root(iid)
        ts = (claimed[r].get("_marker") or {}).get("claimed")
        return f"{r}@{ts[:10]}" if ts else r

    groups = {}
    for iid in sorted(claimed, key=_sort_id_str):
        groups.setdefault(key(iid), []).append(iid)
    landed = {}
    for i in issues:
        if i.get("lane") and i.get("status") in ("verified", "closed") and str(i["lane"]) in groups:
            landed.setdefault(str(i["lane"]), []).append(i)
    out = []
    for k, ids in groups.items():
        inside = set(ids)
        starts = [i for i in ids if parent(i) not in inside or root(i) == i]
        kids = {}
        for i in ids:
            if i not in starts:
                kids.setdefault(parent(i), []).append(i)
        order, todo = [], list(starts)
        while todo:
            cur = todo.pop(0)
            if cur in order:
                continue
            order.append(cur)
            todo.extend(sorted(kids.get(cur, []), key=_sort_id_str))
        order += [i for i in ids if i not in order]
        done = sorted(landed.get(k, []), key=lambda i: (i.get("closed") or "9999", _sort_id_str(i["id"])))
        live = [claimed[x] for x in order]
        members = done + live
        lead_id = k.split("@", 1)[0] if "@" in k else None
        lead = next((m for m in members if m["id"] == lead_id), members[0])
        if lead is not members[0]:
            members = [lead] + [m for m in members if m is not lead]
        heads = [m for m in live if (m.get("_marker") or {}).get("state") in ("active", "pending")]
        stamps = [s for s in ((m.get("_marker") or {}).get("claimed") for m in live) if s]
        out.append({"key": k, "members": members, "lead": lead,
                    "head": heads[0] if heads else live[0],
                    "claimed": min(stamps) if stamps else None})
    out.sort(key=lambda ln: (ln["claimed"] or "9999", _sort_id_str(ln["lead"]["id"])))
    return out


def lane_problems(issues):
    """`--check`'s lane rules (LANES-10).

    A `lane:` value must be `<ID>@<YYYY-MM-DD>`. It stays on an issue that LANDED
    (`verified` / `closed`: the record of which lane resolved it, and what keeps the
    slice whole in the views until its last issue lands) but not on one that went
    back to the queue: a release deletes it. A lane holds AT MOST one ACTIVE or
    PENDING issue -- zero is legal between two issues of a slice. An in-progress
    issue WITHOUT the field is not a problem either: claims made before it existed
    are grouped from their markers, and only the session that owns a claim may write
    to it (INFRA-47).
    """
    out, heads = [], {}
    for it in issues:
        lane = it.get("lane")
        if lane in (None, ""):
            continue
        if it.get("status") not in ("in-progress", "verified", "closed"):
            out.append(f"{it['_path']}: `lane: {lane}` on a `{it.get('status')}` issue — a released "
                       "claim deletes the field with its ⏳ marker")
            continue
        if not LANE_RE.match(str(lane)):
            out.append(f"{it['_path']}: `lane: {lane}` is not `<ID>@<YYYY-MM-DD>`")
        if it.get("status") == "in-progress" and (it.get("_marker") or {}).get("state") in ("active", "pending"):
            heads.setdefault(str(lane), []).append(it["id"])
    for lane, ids in sorted(heads.items()):
        if len(ids) > 1:
            out.append(f"lane {lane}: {len(ids)} ACTIVE/PENDING issues ({', '.join(sorted(ids))}) — "
                       "a lane works one issue at a time")
    return out


def lane_name(ln):
    """A lane is named after its slice: `LANES-20/21/9`, the lead's full ID then the
    others' numbers in slice order (a member from another project keeps its full
    ID: `LANES-22/INFRA-100`). The lead comes from the recorded key, so the name
    stays the same after the lead lands and only its reservations remain."""
    lead = ln["key"].split("@", 1)[0] if "@" in ln["key"] else ln["lead"]["id"]
    ids = [lead] + [m["id"] for m in ln["members"] if m["id"] != lead]
    proj = lead.rsplit("-", 1)[0]
    return "/".join([ids[0]] + [i.rsplit("-", 1)[1] if i.rsplit("-", 1)[0] == proj else i
                                for i in ids[1:]])


def lane_label(ln):
    """How every view describes a lane: its slice name, then where the head issue is."""
    head = ln["head"].get("_marker") or {}
    if head.get("worktree"):
        where = head["worktree"]
    elif head.get("state") == "pending":
        where = "worktree pending"
    else:
        where = "between issues" if len(ln["members"]) > 1 else "not started"
    return {"name": lane_name(ln), "where": where, "branch": head.get("branch"),
            "machine": head.get("machine") or head.get("who"), "claimed": ln["claimed"],
            "key": ln["key"]}


def lane_member_state(m):
    """active / pending / reserved for a claim; landed / closed for a member that is done."""
    if m.get("status") == "verified":
        return "landed"
    if m.get("status") == "closed":
        return "closed"
    return (m.get("_marker") or {}).get("state") or "unknown"


def lane_member_note(ln, m):
    """A reservation queued behind an issue that is neither claimed nor in its lane says so."""
    mk = m.get("_marker") or {}
    if (m.get("status") == "in-progress" and mk.get("state") == "reserved" and mk.get("behind")
            and mk["behind"] not in {x["id"] for x in ln["members"]}):
        return f"queued behind {mk['behind']}, no longer claimed"
    return ""

def _sort_id_str(iid):
    proj, _, num = (iid or "").partition("-")
    return f"{proj}-{int(num):04d}" if num.isdigit() else (iid or "")


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
        # A FIXED abbreviation (LANES-6): git's default length scales with each clone's
        # object count, so two machines could otherwise cite one commit two ways.
        proc = subprocess.run(["git", "log", "--abbrev=7", "--format=%H%x00%h%x00%s", "HEAD"], cwd=ROOT,
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
            + dangling_epics(issues) + resolution_problems(issues) + lane_problems(issues))


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


def commit_date(full_hash):
    """The commit's committer date as YYYY-MM-DD (in the committer's own zone, so every
    clone reads the same string), or None if git can't answer."""
    try:
        proc = subprocess.run(["git", "log", "-1", "--format=%cs", full_hash], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = proc.stdout.strip()
    return out if proc.returncode == 0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", out) else None


def backfill_verified(issues, subjects=None, today=None, dry_run=False):
    """Close every `verified` issue whose cited subject is on HEAD.

    For each: `commit:` <- the resolving commit's abbreviated hash, `status:` <-
    closed, `closed:` <- the resolving commit's committer date if it was null (a
    lane that dated it keeps its date; `today` only when git cannot date the
    commit). The commit date, not the day the backfill ran, is what makes two
    machines' closes of one issue byte-identical (LANES-6). Nothing else in the file changes. Verified issues with no resolvable
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
            updates["closed"] = commit_date(full) or today
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


def _git_run(*args):
    """(returncode, stdout, stderr) of a git command in ROOT; never raises."""
    try:
        proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _ancestor(a, b):
    return _git_run("merge-base", "--is-ancestor", a, b)[0] == 0


def sync_main():
    """Before a --push backfill: fetch, and fast-forward the main branch if it is behind,
    so the scan only closes what origin still shows as verified. Returns an error string,
    or None when HEAD now contains `origin/<main>`."""
    branch = _git_run("rev-parse", "--abbrev-ref", "HEAD")[1]
    if branch != MAIN_BRANCH:
        return f"--push runs on `{MAIN_BRANCH}`; this checkout is on `{branch}`"
    rc, _, err = _git_run("fetch", "-q", "origin", MAIN_BRANCH)
    if rc:
        return f"git fetch origin {MAIN_BRANCH} failed: {err}"
    upstream = f"origin/{MAIN_BRANCH}"
    if _ancestor(upstream, "HEAD"):
        return None
    if _ancestor("HEAD", upstream):
        rc, _, err = _git_run("merge", "-q", "--ff-only", upstream)
        return f"fast-forward to {upstream} failed: {err}" if rc else None
    return (f"local `{MAIN_BRANCH}` and {upstream} have diverged — pull with --rebase first, "
            "then re-run the backfill")


def guard_cfg():
    """The slice of the resolved config `push_guard` reads, from this module's globals --
    so `isolated()`'s repointing carries over to the guard too."""
    return {"main_branch": MAIN_BRANCH, "ok_free_paths": list(OK_FREE_PATHS),
            "main_direct_paths": [], "backlog_dir": BACKLOG_REL, "machine": MACHINE}


def push_backfill(attempts=3):
    """Push the main branch after a backfill commit, converging on a rejected push.

    The OK-free push guard (`push_guard.py --ok-free`, LANES-5): every commit ahead of
    origin must sit under `git.ok_free_paths`, and none may edit another machine's
    claim; anything else on local main needs the operator's OK, so the backfill commit
    stays local. On a rejection -- another certifying machine pushed first -- fetch and
    rebase: an identical close merges cleanly or drops out as already upstream. Never
    forces. Returns (ok, message).

    The guard's `--check` leg is skipped HERE: the backfill already refused on any
    structural problem, and a verified issue it SKIPPED leaves `--check` red for a reason
    that must not hold back the closes that are right. The skip is reported on its own."""
    code, msg = push_guard.push(ROOT, guard_cfg(), push_guard.OK_FREE, attempts=attempts,
                                run_check=False)
    if code == push_guard.REFUSED:
        return False, f"not pushed — {msg}; push them with the operator's OK"
    return code == 0, msg


def isolated(fn):
    """Run fn() with this module pointed at a throwaway worktree, detached at a freshly
    fetched `origin/<main>`; remove the worktree afterwards, whatever fn() did (LANES-23).

    The main clone is shared by every session on the machine, and a claim is committed
    there before it is pushed. A close that runs in it can meet another session's
    half-made commit: refusing on the divergence is correct, but it fails exactly when
    sessions are busy. The throwaway worktree starts from what origin has, so nothing
    local is in its way, and it never touches the main clone's branch, index or files.
    A close that could not push is discarded with the worktree: it is deterministic, so
    the next backfill redoes it byte for byte. Returns fn()'s result, or an error string
    when the worktree could not be made."""
    paths = ("ROOT", "BACKLOG", "INDEX", "HTML_VIEW")
    home = {k: globals()[k] for k in paths}
    rc, _, err = _git_run("fetch", "-q", "origin", MAIN_BRANCH)
    if rc:
        return f"git fetch origin {MAIN_BRANCH} failed: {err}"
    tmp = Path(tempfile.mkdtemp(prefix="lanes-backfill-"))
    wt = tmp / ROOT.name
    rc, _, err = _git_run("worktree", "add", "-q", "--detach", str(wt), f"origin/{MAIN_BRANCH}")
    if rc:
        shutil.rmtree(tmp, ignore_errors=True)
        return f"could not make a worktree at origin/{MAIN_BRANCH}: {err}"
    try:
        apply({"ROOT": wt, "BACKLOG": wt / BACKLOG_REL, "INDEX": wt / BACKLOG_REL / "INDEX.md",
               "HTML_VIEW": wt / BACKLOG_REL / "index.html"})   # same config, the worktree's files
        return fn()
    finally:
        apply(home)                                   # _git_run runs in ROOT: the caller's clone again
        _git_run("worktree", "remove", "--force", str(wt))
        shutil.rmtree(tmp, ignore_errors=True)
        _git_run("worktree", "prune")


def _cell(v):
    return (v if v not in (None, "", []) else "—")


def _md_lanes(lanes):
    """INDEX.md's In progress section: one block per lane, issues in slice order."""
    if not lanes:
        return []
    n = sum(1 for ln in lanes for m in ln["members"] if m.get("status") == "in-progress")
    out = ["", f"## In progress — {n} claimed · {len(lanes)} lane{'s' if len(lanes) != 1 else ''}"]
    for ln in lanes:
        lb = lane_label(ln)
        bits = [f"**{lb['name']}**", f"`{lb['where']}`" + (f" (`{lb['branch']}`)" if lb["branch"] else "")]
        bits += [x for x in (lb["machine"], f"claimed {lb['claimed']}" if lb["claimed"] else None) if x]
        bits.append(f"lane `{lb['key']}`")
        out += ["", " · ".join(bits), ""]
        for m in ln["members"]:
            state = lane_member_state(m)
            note = lane_member_note(ln, m)
            out.append(f"- {state} · [{m['id']}]({m['_path'].as_posix().replace(BACKLOG_REL + '/', '')}) "
                       f"— {m['_title']}" + (f" _({note})_" if note else ""))
    return out


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
    lines += _md_lanes(lanes_in_flight(issues))
    lines += [
        "",
        "## Open / blocked / paused",
        "",
        "| ID | Type | Status | Pri | Assignee | Opened | Epic | Blocked on | Title |",
        "| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |",
    ]
    # A claimed issue is listed once, under its lane, not again in the queue.
    for i in sorted((i for i in open_issues if i.get("status") != "in-progress"), key=sort_key):
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

# Title sits right after the ID because it is the one field every row is read
# for (LANES-22); blocked-on rides under it on one clamped line instead of
# owning a column that wrapped rows to nine lines. `Opened` left the live
# table: Age sorts identically and says it in fewer characters.
OPEN_COLS = (("ID", "id", 0), ("Title", "title", 0), ("Pri", "priorityRank", 1),
             ("Status", "statusRank", 1), ("Type", "type", 0), ("Assignee", "assignee", 0),
             ("Epic", "epic", 0), ("Age", "age", 1))
CLOSED_COLS = (("ID", "id", 0), ("Title", "title", 0), ("Pri", "priorityRank", 1),
               ("Type", "type", 0), ("Assignee", "assignee", 0), ("Closed", "closed", 0),
               ("Resolution", "resolution", 0), ("Commit", "commit", 0))
VERIFIED_COLS = (("ID", "id", 0), ("Title", "title", 0), ("Pri", "priorityRank", 1),
                 ("Type", "type", 0), ("Assignee", "assignee", 0), ("Age", "age", 1))
# Dropped first on a narrow screen, so a phone still gets ID / title / pri / status.
SECONDARY_COLS = ("type", "assignee", "epic", "opened", "commit", "resolution")

HTML_STYLE = """
:root{color-scheme:light dark;
  --bg:#f6f7f9;--surface:#fff;--fg:#17191c;--mut:#646b75;--faint:#9aa1ab;--line:#e4e7eb;
  --hov:#f2f4f7;--chip:#eef0f3;--accent:#2f5bd3;--accent-soft:#e7edfb;
  --warn-bg:#fff7e6;--warn-fg:#7a4b00;--warn-line:#f3d79b;
  --ok:#1f8a4c;--act:#2f5bd3;--pend:#b7791f;--res:#8a94a3;
  --shadow:0 1px 2px rgba(16,24,40,.05)}
@media (prefers-color-scheme:dark){:root{
  --bg:#0f1114;--surface:#16191e;--fg:#e6e8eb;--mut:#9aa1ab;--faint:#6b727c;--line:#262a31;
  --hov:#1d2127;--chip:#20242b;--accent:#8aa9ff;--accent-soft:#1c2540;
  --warn-bg:#2a2112;--warn-fg:#f3c776;--warn-line:#4a3a1a;
  --ok:#4cc184;--act:#8aa9ff;--pend:#e0a948;--res:#79818d;
  --shadow:none}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);
     font:13.5px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Helvetica,Arial,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:22px 24px 64px}
a{color:inherit;text-decoration:none}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.92em}
.top{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:6px 16px}
h1{font-size:20px;letter-spacing:-.01em;margin:0;font-weight:650}
h1 .repo{color:var(--mut);font-weight:450}
.meta{color:var(--mut);font-size:12px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.pos::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;
             background:var(--ok);margin-right:6px;vertical-align:1px}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 18px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:10px;
      padding:7px 12px;box-shadow:var(--shadow);color:var(--mut);font-size:12px}
.stat b{display:block;font-size:18px;line-height:1.2;color:var(--fg);font-weight:650;
        font-variant-numeric:tabular-nums}
.stat.crit b{color:#c0352b}
@media (prefers-color-scheme:dark){.stat.crit b{color:#ff8a80}}
.callout{background:var(--warn-bg);color:var(--warn-fg);border:1px solid var(--warn-line);
         border-radius:10px;padding:9px 13px;margin:0 0 14px;font-size:12.5px}
.callout summary{cursor:pointer;font-weight:600}
.callout ul{margin:6px 0 0;padding-left:18px;max-height:14rem;overflow:auto}
.callout li{margin:2px 0;word-break:break-word}
h2{font-size:13px;font-weight:650;margin:0 0 10px;display:flex;align-items:baseline;gap:8px}
h2 small{color:var(--mut);font-weight:450;font-size:12px}
.lanes{margin-bottom:22px}
.lane-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(440px,1fr));gap:12px;align-items:start}
.lane{background:var(--surface);border:1px solid var(--line);border-radius:12px;
      box-shadow:var(--shadow);overflow:hidden}
.lane>header{padding:10px 14px 9px;border-bottom:1px solid var(--line);font-size:12px;
             color:var(--mut);display:flex;flex-direction:column;gap:2px}
.lane>header .ln{color:var(--fg);font-weight:600;font-size:13px;display:flex;gap:8px;
                 align-items:baseline;flex-wrap:wrap}
.lane>header .ln code{color:var(--mut);font-weight:450}
.lane ol{list-style:none;margin:0;padding:4px 0}
.lane li{display:grid;grid-template-columns:auto auto 1fr;gap:10px;align-items:baseline;
         padding:6px 14px}
.lane li:hover{background:var(--hov)}
.lane li .t{min-width:0}
.lane li.reserved .t{color:var(--mut)}
.lane .after{display:block;font-size:11.5px;color:var(--faint)}
.st{font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;
    display:inline-flex;align-items:center;gap:5px;color:var(--mut);min-width:5.6rem}
.st::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--res)}
.st-active{color:var(--act)}.st-active::before{background:var(--act);
           box-shadow:0 0 0 3px var(--accent-soft)}
.st-pending{color:var(--pend)}.st-pending::before{background:var(--pend)}
.st-reserved::before{background:transparent;border:1.5px solid var(--res)}
.st-landed,.st-closed{color:var(--ok)}
.st-landed::before,.st-closed::before{content:"\\2713";width:auto;height:auto;background:none;
                                      font-size:11px;line-height:1}
.lane li.landed .t,.lane li.closed .t{color:var(--mut)}
.lane li.landed a.id,.lane li.closed a.id{color:var(--mut)}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
#q{flex:1 1 260px;max-width:440px;padding:8px 12px;font:inherit;color:var(--fg);
   background:var(--surface);border:1px solid var(--line);border-radius:8px}
#q:focus{outline:2px solid var(--accent);outline-offset:-1px}
button{font:inherit;font-size:12.5px;padding:7px 12px;border-radius:8px;cursor:pointer;
       border:1px solid var(--line);background:var(--surface);color:var(--fg)}
button:hover{background:var(--hov)}
button[aria-expanded="true"]{background:var(--accent-soft);border-color:transparent;color:var(--accent)}
#fcount{display:inline-block;min-width:1.4em;margin-left:4px;padding:0 5px;border-radius:9px;
        background:var(--accent);color:var(--surface);font-size:11px;font-weight:600}
#fcount:empty{display:none}
#showing{color:var(--mut);font-size:12px;margin:0 0 0 auto}
.facets{background:var(--surface);border:1px solid var(--line);border-radius:10px;
        padding:10px 12px;margin-bottom:12px}
.facets[hidden]{display:none}
fieldset{border:0;margin:0 0 6px;padding:0;display:flex;flex-wrap:wrap;align-items:center;gap:5px}
fieldset:last-child{margin-bottom:0}
.flabel{color:var(--mut);font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;
        flex:0 0 5.2rem;font-weight:600}
.allbtn{font-size:11px;padding:2px 8px;border-radius:20px;border:1px dashed var(--line);
        background:transparent;color:var(--mut)}
.allbtn:hover{color:var(--fg);border-style:solid}
label.chip{display:inline-flex;align-items:center;gap:5px;background:var(--chip);
           border:1px solid transparent;border-radius:20px;padding:2px 9px 2px 6px;
           cursor:pointer;user-select:none;font-size:12px}
label.chip:hover{border-color:var(--line)}
label.chip input{margin:0;accent-color:var(--accent)}
label.chip .c{color:var(--faint);font-variant-numeric:tabular-nums}
label.chip.off{opacity:.45}
details.sec{background:var(--surface);border:1px solid var(--line);border-radius:12px;
            box-shadow:var(--shadow);margin-bottom:14px}
details.sec>summary{cursor:pointer;font-weight:650;padding:11px 14px;font-size:13px;
                    list-style:none;display:flex;gap:6px;align-items:baseline}
details.sec>summary::-webkit-details-marker{display:none}
details.sec>summary::before{content:"\\25B8";color:var(--faint);font-size:11px;
                            transition:transform .12s;display:inline-block}
details.sec[open]>summary::before{transform:rotate(90deg)}
details.sec>summary .n{color:var(--mut);font-weight:450}
table{border-collapse:separate;border-spacing:0;width:100%}
th,td{text-align:left;padding:8px 12px;border-top:1px solid var(--line);vertical-align:top}
thead th{position:sticky;top:0;z-index:1;background:var(--surface);cursor:pointer;
         white-space:nowrap;font-size:10.5px;font-weight:600;text-transform:uppercase;
         letter-spacing:.05em;color:var(--mut);user-select:none}
thead th:hover{color:var(--fg)}
thead th.asc::after{content:" \\25B2";font-size:8px}
thead th.desc::after{content:" \\25BC";font-size:8px}
tbody tr:hover{background:var(--hov)}
td{color:var(--mut);font-size:12.5px}
td.id{white-space:nowrap}
td.id a,.lane a.id{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
                   font-size:12px;color:var(--accent)}
td.id a:hover,.lane a.id:hover,td.title a:hover{text-decoration:underline}
td.title{color:var(--fg);font-size:13.5px;width:52%;min-width:16rem}
td.title a{display:block}
.why{color:var(--mut);font-size:12px;margin-top:2px;overflow:hidden;max-width:62ch;
     display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:1;line-clamp:1;
     overflow-wrap:anywhere}
.why::before{content:"blocked on ";color:var(--faint)}
td.num,td.date{white-space:nowrap;font-variant-numeric:tabular-nums}
td.commit{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11.5px}
.pill{display:inline-block;border-radius:20px;padding:1px 8px 2px;font-size:11px;
      white-space:nowrap;background:var(--chip);color:var(--mut);font-weight:500}
.p-critical{background:#fde4e1;color:#a8261b}
.p-high{background:#ffeedd;color:#9a4210}
.s-in-progress{background:#e2eaff;color:#2445a8}
.s-blocked{background:#fff1cc;color:#865300}
.s-paused{background:#efe8ff;color:#5b3bb0}
.s-verified{background:#dcf5e6;color:#17663a}
@media (prefers-color-scheme:dark){
  .p-critical{background:#45201d;color:#ff9d93}
  .p-high{background:#43291a;color:#ffb37a}
  .s-in-progress{background:#1d2a4d;color:#9db7ff}
  .s-blocked{background:#3d3015;color:#f5cf6e}
  .s-paused{background:#2d2448;color:#c7b4ff}
  .s-verified{background:#173526;color:#7fdba6}}
.empty{color:var(--mut);padding:4px 14px 14px;margin:0}
footer{color:var(--faint);font-size:11.5px;margin-top:26px;line-height:1.6}
@media (max-width:720px){
  .wrap{padding:16px 16px 48px}
  .lane-grid{grid-template-columns:1fr}
  .col-sec,.col-age{display:none}
  th,td{padding:8px 6px}
  td.title{min-width:0;width:auto;overflow-wrap:anywhere}
  .lane li{grid-template-columns:auto 1fr;row-gap:2px}
  .lane li .t{grid-column:1/-1}
  .why{max-width:none}
  #showing{flex-basis:100%;margin:0}
  .flabel{flex-basis:100%}}
"""

HTML_SCRIPT = """
const norm = s => (s || '').toLowerCase();
const tables = () => Array.from(document.querySelectorAll('table.issues'));
const bodyRows = t => Array.from(t.tBodies[0].rows);
const store = {get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
               set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} }};

function checked(field){
  const boxes = document.querySelectorAll('fieldset[data-field="' + field + '"] input');
  const on = new Set();
  boxes.forEach(b => { b.parentElement.classList.toggle('off', !b.checked);
                       if (b.checked) on.add(b.value); });
  const btn = document.querySelector('.allbtn[data-all="' + field + '"]');
  if (btn) btn.textContent = on.size === boxes.length ? 'none' : 'all';
  return {on, any: boxes.length > 0, narrowed: boxes.length > 0 && on.size < boxes.length};
}

function applyFilter(){
  const q = norm(document.getElementById('q').value).trim();
  const f = {project: checked('project'), status: checked('status'),
             priority: checked('priority'), assignee: checked('assignee'),
             epic: checked('epic')};
  const active = (q ? 1 : 0) + Object.values(f).filter(c => c.narrowed).length;
  let shown = 0, total = 0;
  tables().forEach(t => {
    let n = 0;
    bodyRows(t).forEach(r => {
      total++;
      const d = r.dataset;
      // An epic row lists itself AND its parent, a child lists its parent, so
      // one chip shows the whole family (INFRA-52). A repo with no epics has no
      // epic row of chips, and then the epic test must pass, not hide every row.
      const ok = f.project.on.has(d.project) && f.status.on.has(d.status)
              && f.priority.on.has(d.priority) && f.assignee.on.has(d.assignee)
              && (!f.epic.any || d.epics.split(' ').some(e => f.epic.on.has(e)))
              && (!q || d.haystack.includes(q));
      r.hidden = !ok;
      if (ok) { n++; shown++; }
    });
    t.closest('details').querySelector('.n').textContent = n;
  });
  document.getElementById('showing').textContent =
    shown === total ? total + ' issues' : 'showing ' + shown + ' of ' + total + ' issues';
  document.getElementById('fcount').textContent = active ? active : '';
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

// Claim times are written LOCAL ("YYYY-MM-DD HH:MM"); say how long ago, which
// is the question a stale-claim glance actually asks.
function ago(){
  const now = Date.now();
  document.querySelectorAll('time[data-ts]').forEach(t => {
    const m = t.dataset.ts.match(/^(\\d{4})-(\\d{2})-(\\d{2})(?: (\\d{2}):(\\d{2}))?$/);
    if (!m) return;
    const d = new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0));
    const min = Math.max(0, Math.round((now - d) / 60000));
    t.textContent = !m[4] ? t.dataset.ts
      : min < 1 ? 'just now' : min < 60 ? min + 'm ago'
      : min < 48 * 60 ? Math.round(min / 60) + 'h ago' : Math.round(min / 1440) + 'd ago';
    t.title = t.dataset.ts;
  });
}

const facets = document.getElementById('facets'), toggle = document.getElementById('ftoggle');
function showFacets(open){
  facets.hidden = !open;
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  store.set('lanes.backlog.filters', open ? '1' : '0');
}
toggle.addEventListener('click', () => showFacets(facets.hidden));
showFacets(store.get('lanes.backlog.filters') === '1');

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
ago();
setInterval(ago, 60000);
"""


def _esc(v):
    return html.escape("" if v is None else str(v))


def _pill(kind, value):
    if not value:
        return '<span class="pill">—</span>'
    return f'<span class="pill {kind}-{_esc(value)}">{_esc(value)}</span>'


def _facet(field, values, counts=None):
    counts = counts or {}
    chips = "".join(
        f'<label class="chip"><input type="checkbox" value="{_esc(v)}" checked>{_esc(v)}'
        + (f' <span class="c">{counts[v]}</span>' if counts.get(v) else "") + '</label>'
        for v in values)
    return (f'<fieldset data-field="{field}"><span class="flabel">{field}</span>'
            f'<button type="button" class="allbtn" data-all="{field}">none</button>{chips}</fieldset>')


def _href(i):
    return i["_path"].as_posix().replace(BACKLOG_REL + "/", "")


def _html_row(i, cols):
    href = _href(i)
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
    why = i.get("blocked_on")
    why_html = (f'<div class="why" title="{_esc(why)}">{_esc(why)}</div>'
                if why and i.get("status") in LIVE_STATUSES else "")
    cells = {
        "id": ("id", f'<a href="{_esc(href)}">{_esc(i["id"])}</a>'),
        "title": ("title", f'<a href="{_esc(href)}">{_esc(title)}</a>{why_html}'),
        "priorityRank": ("", _pill("p", i.get("priority"))),
        "statusRank": ("", _pill("s", i.get("status"))),
        "type": ("", _esc(i.get("type"))),
        "assignee": ("", _esc(i.get("assignee") or "—")),
        "opened": ("date", _esc(i.get("opened") or "—")),
        "closed": ("date", _esc(i.get("closed") or "—")),
        "commit": ("commit", _esc(i.get("commit") or "—")),
        "resolution": ("", _esc(i.get("resolution") or "—")),
        "age": ("num", f"{age}d" if age is not None else "—"),
        "epic": ("id", _esc(i.get("epic") or "—")),
    }

    def td(key):
        cls, inner = cells[key]
        classes = " ".join(c for c in (cls, _col_class(key)) if c)
        return f'<td class="{classes}">{inner}</td>' if classes else f"<td>{inner}</td>"

    attr_str = " ".join(f'data-{k}="{_esc(v)}"' for k, v in attrs.items())
    return f"<tr {attr_str}>" + "".join(td(key) for _, key, _n in cols) + "</tr>"


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
    return _sort_id_str(i.get("id"))


def _col_class(key):
    """`col-sec` columns drop first on a narrow screen; `col-age` drops with them."""
    return "col-sec" if key in SECONDARY_COLS else "col-age" if key == "age" else ""


def _html_table(issues, cols, empty):
    if not issues:
        return f'<p class="empty">{empty}</p>'
    head = "".join(
        f'<th data-key="{key}" data-num="{num}"'
        + (f' class="{_col_class(key)}"' if _col_class(key) else "") + f'>{_esc(label)}</th>'
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


def _html_lanes(lanes):
    """The In progress section: one card per lane, issues in slice order."""
    if not lanes:
        return ""
    cards = []
    for ln in lanes:
        lb = lane_label(ln)
        name = lb["name"]
        branch = f' <code>{_esc(lb["where"])}</code>' + (f' <code>{_esc(lb["branch"])}</code>'
                                                         if lb["branch"] else "")
        who = _esc(lb["machine"] or "")
        when = (f'claimed <time data-ts="{_esc(ln["claimed"])}">{_esc(ln["claimed"])}</time>'
                if ln["claimed"] else "claim time unreadable")
        items = []
        for m in ln["members"]:
            state = lane_member_state(m)
            pri = (" " + _pill("p", m.get("priority"))
                   if m.get("priority") in ("critical", "high") else "")
            note = lane_member_note(ln, m)
            after = f'<span class="after">{_esc(note)}</span>' if note else ""
            items.append(
                f'<li class="{state}"><span class="st st-{state}">{state}</span>'
                f'<a class="id" href="{_esc(_href(m))}">{_esc(m["id"])}</a>'
                f'<span class="t">{_esc(m["_title"])}{pri}{after}</span></li>')
        cards.append(
            f'<article class="lane" title="lane {_esc(ln["key"])}"><header><span class="ln">{_esc(name)}{branch}</span>'
            f'<span>{who + " · " if who else ""}{when}</span></header>'
            f'<ol>{"".join(items)}</ol></article>')
    n = sum(1 for ln in lanes for m in ln["members"] if m.get("status") == "in-progress")
    lanes_word = "lane" if len(lanes) == 1 else "lanes"
    return (f'<section class="lanes"><h2>In progress <small>{n} claimed · {len(lanes)} '
            f'{lanes_word}</small></h2><div class="lane-grid">{"".join(cards)}</div></section>')


def _html_problems(problems):
    if not problems:
        return ""
    items = "".join(f"<li>{html.escape(p)}</li>" for p in problems)
    noun = "problem" if len(problems) == 1 else "problems"
    return (f'<details class="callout"><summary>⚠️ {len(problems)} backlog {noun} — run '
            f'<code>backlog_index.py --check</code></summary><ul>{items}</ul></details>')


def render_html(issues, problems=(), position=None):
    for i in issues:
        i["_age"] = _age(i.get("opened"))
    live = [i for i in issues if i.get("status") in LIVE_STATUSES]
    lanes = lanes_in_flight(issues)
    # A claimed issue is shown once, in its lane card, not again in the queue.
    open_issues = sorted((i for i in live if i.get("status") != "in-progress"), key=html_sort_key)
    verified = sorted((i for i in issues if i.get("status") == "verified"), key=html_sort_key)
    closed = sorted((i for i in issues if i.get("status") == "closed"),
                    key=lambda x: (x.get("closed") or "", x.get("id") or ""), reverse=True)
    tabled = open_issues + verified + closed

    present = lambda field, vocab: [v for v in vocab if any(i.get(field) == v for i in tabled)]
    assignees = sorted({i.get("assignee") or "—" for i in tabled})
    epics = sorted({i["id"] for i in issues if i.get("type") == "epic" and i.get("id")}
                   | {i["epic"] for i in issues if i.get("epic")},
                   key=lambda e: _sort_id({"id": e}))
    live_by_proj = {}
    for i in live:
        live_by_proj[i.get("project")] = live_by_proj.get(i.get("project"), 0) + 1
    facets = "".join((
        _facet("project", present("project", PROJECTS), live_by_proj),
        _facet("status", present("status", STATUSES)),
        _facet("priority", present("priority", PRIORITIES)),
        _facet("assignee", assignees),
        _facet("epic", epics + ["—"]) if epics else "",
    ))

    n_claimed = sum(1 for ln in lanes for m in ln["members"] if m.get("status") == "in-progress")
    n_crit = sum(1 for i in live if i.get("priority") == "critical")
    stats = "".join((
        f'<div class="stat"><b>{len(live)}</b> live</div>',
        f'<div class="stat"><b>{n_claimed}</b> in progress</div>',
        f'<div class="stat crit"><b>{n_crit}</b> critical</div>' if n_crit else "",
        f'<div class="stat"><b>{len(verified)}</b> verified</div>',
        f'<div class="stat"><b>{len(closed)}</b> closed</div>',
    ))
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    pos_inline, banner = "", ""
    if position:
        b = _banner(*position)
        pos_inline, banner = ("", b) if position[1] else (b, "")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backlog — {_esc(REPO_NAME)}</title>
<style>{HTML_STYLE}</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <h1>Backlog <span class="repo">· {_esc(REPO_NAME)}</span></h1>
  <div class="meta">{pos_inline}<span>generated {stamp}</span></div>
</header>
<div class="stats">{stats}</div>
{banner}
{_html_problems(problems)}
{_html_lanes(lanes)}
<div class="bar">
  <input id="q" type="search" placeholder="Filter — id, title, assignee, reporter, resolution, blocked-on, links…"
         autocomplete="off" spellcheck="false">
  <button id="ftoggle" type="button" aria-expanded="false" aria-controls="facets">Filters<span id="fcount"></span></button>
  <button id="reset" type="button">Reset</button>
  <p id="showing"></p>
</div>
<div id="facets" class="facets" hidden>{facets}</div>
<details class="sec" open>
  <summary>Open queue <span class="n">{len(open_issues)}</span></summary>
  {_html_table(open_issues, OPEN_COLS, "No open issues.")}
</details>
<details class="sec" {"open" if verified else ""}>
  <summary>Verified — landed, awaiting {html.escape(CERTIFIER_LABEL, quote=False)} close <span class="n">{len(verified)}</span></summary>
  {_html_table(verified, VERIFIED_COLS, "Nothing awaiting close.")}
</details>
<details class="sec">
  <summary>Closed <span class="n">{len(closed)}</span></summary>
  {_html_table(closed, CLOSED_COLS, "No closed issues yet.")}
</details>
<footer>Generated by the lanes plugin's <code>backlog_index.py</code> — a local, gitignored view; never
hand-edit it. The issue files under <code>{_esc(BACKLOG_REL)}/&lt;PROJECT&gt;/</code> are the source of truth.</footer>
</div>
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
    lanes = lanes_in_flight(issues)
    if lanes:
        # Every operator's lanes, not just this one's: a claim is a wall for everyone.
        n = sum(1 for ln in lanes for m in ln["members"] if m.get("status") == "in-progress")
        print(f"{'='*100}\nIN PROGRESS — {n} claimed · {len(lanes)} lane{'s' if len(lanes) != 1 else ''}"
              f" (claims are walls: route around every issue here)\n{'='*100}")
        for ln in lanes:
            lb = lane_label(ln)
            bits = [lb["name"], lb["where"] + (f" [{lb['branch']}]" if lb["branch"] else "")]
            bits += [x for x in (lb["machine"], f"claimed {lb['claimed']}" if lb["claimed"] else None) if x]
            print("  " + " · ".join(bits + [f"lane {lb['key']}"]))
            for m in ln["members"]:
                state = lane_member_state(m)
                note = lane_member_note(ln, m)
                # Full titles: the lane block is short, and the title is what the eye reads.
                print(f"      {state:<9} {m['id']:>10}  {m['_title']}" + (f"  ({note})" if note else ""))
        print()
    print(f"{'='*100}\nBACKLOG ({who}) — {len(mine)} live\n{'='*100}")
    for i in sorted((i for i in mine if i.get("status") != "in-progress"),
                    key=lambda x: (x["_age"] is None, -(x["_age"] or 0))):
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
    HTML_VIEW.write_text(render_html(issues, problems), encoding="utf-8")
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
    """The served view's clone position: an inline note when level, a callout when behind."""
    if head is None:
        return ""
    if behind:
        return (f'<div class="callout"><strong>This clone is {behind} commit(s) behind '
                f'<code>origin/{_esc(MAIN_BRANCH)}</code></strong> (HEAD <code>{head}</code>, as of its last '
                f'fetch) — a lane that landed from a worktree will not appear until you pull.</div>')
    return (f'<span class="pos" title="Rendered live at each request">'
            f'<code>{head}</code> · level with <code>origin/{_esc(MAIN_BRANCH)}</code></span>')


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
            body = render_html(issues, problems, position=clone_position())
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


def run_backfill(args, issues=None, isolated=False):
    """Close, report, and (per args) commit and push. `isolated`: running inside
    isolated(), where the views are not regenerated -- they would be written into the
    throwaway worktree and deleted with it."""
    if issues is None:
        issues, problems = load_issues()
        for p in problems:
            print(f"⚠️  {p}", file=sys.stderr)
        if problems:
            print("backfill refused — fix the structural problems above first", file=sys.stderr)
            return 1
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
        if not isolated:
            regenerate()
        if args.do_commit:
            subject = commit_backfill(closed)
            if args.push:
                ok, msg = push_backfill()
                print(f"committed: {subject}  ({msg})", file=None if ok else sys.stderr)
                if not ok:
                    if isolated:
                        print("  the close was discarded with the throwaway worktree; it is "
                              "deterministic, so the next backfill redoes it", file=sys.stderr)
                    return 1
            else:
                print(f"committed: {subject}  (not pushed)")
        else:
            paths = " ".join(str(it["_path"]) for it, _ in closed)
            print(f"not committed — stage by path: git add -- {paths}")
    return 1 if skipped else 0


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
                    help="with --backfill: git add the closed issue files by path and commit")
    ap.add_argument("--push", action="store_true",
                    help="with --backfill: fetch and fast-forward first, then commit and push; on a "
                         "rejected push, rebase and retry (several certifying machines may run it at once)")
    ap.add_argument("--isolated", action="store_true",
                    help="with --backfill --push: close and push from a throwaway worktree at a freshly "
                         "fetched origin/<main>, never touching this checkout (what lanes_land.py runs)")
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
              "no orphaned claims, no orphaned commit citations, no dangling epics, no lane conflicts, "
              f"{n_verified} verified awaiting backfill (each documented).")
        return 0

    if args.backfill:
        if problems:
            print("backfill refused — fix the structural problems above first", file=sys.stderr)
            return 1
        if not certifies():
            print(f"backfill refused — this clone is {machine_id()!r} "
                  f"(git user.name {git_user_name()!r} + platform {sys.platform!r}), and its "
                  "operator row does not certify. The backfill closes issues on the operator's "
                  "behalf, so only a certifying machine runs it. Verified issues are read-only "
                  "here.", file=sys.stderr)
            return 2
        if args.isolated and not args.push:
            print("--isolated needs --push — it exists to push a close past a busy checkout",
                  file=sys.stderr)
            return 2
        if args.push:
            if args.dry_run:
                print("--push and --dry-run do not combine — --dry-run writes nothing", file=sys.stderr)
                return 2
            args.do_commit = True
            if args.isolated:
                out = isolated(lambda: run_backfill(args, isolated=True))
                if isinstance(out, str):
                    print(f"backfill refused — {out}", file=sys.stderr)
                    return 1
                return out
            err = sync_main()
            if err:
                print(f"backfill refused — {err}", file=sys.stderr)
                return 1
            issues, problems = load_issues()
            if problems:
                for p in problems:
                    print(f"⚠️  {p}", file=sys.stderr)
                print("backfill refused — fix the structural problems above first", file=sys.stderr)
                return 1
        return run_backfill(args, issues)

    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(render_index(issues), encoding="utf-8")
    HTML_VIEW.write_text(render_html(issues, problems), encoding="utf-8")
    print(f"wrote {INDEX.relative_to(ROOT)} + {HTML_VIEW.relative_to(ROOT)} "
          f"(local, gitignored) — {len(issues)} issues"
          + (f", {len(problems)} problem(s) above" if problems else ""))
    print(f"  sortable view → {HTML_VIEW.as_uri()}")
    if args.open_view:
        webbrowser.open(HTML_VIEW.as_uri())
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
