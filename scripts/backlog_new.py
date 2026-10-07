"""Create a new backlog issue file with the next free ID for its project.

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage:
  python3 backlog_new.py CORE "modify_endpoint inference gaps" --type=bug --priority=high --reported-by=<short>
  python3 backlog_new.py INFRA "add fixtures" --type=story --assignee=<short> --reported-by=claude
  python3 backlog_new.py CORE "invite-only registration" --epic=CORE-14 --reported-by=<short>
  python3 backlog_new.py CORE "a title" --reported-by=me     # this machine's operator (/lanes:new)

Projects, types, priorities, assignees and reporters come from the lanes config
(`backlog_index` resolves it once at import). `--reported-by` is REQUIRED: a default
would silently mis-attribute, and `claude` is always a valid reporter. `--reported-by=me`
names this machine's operator row; it is refused on a machine with no row in a
multi-operator repo.

ID assignment is scan-based -- next number = max(seen) + 1, computed at creation
time. No counter file: a counter could silently hand out the same ID twice, whereas
two lanes creating the same filename collide as a VISIBLE git add/add conflict.

"Seen" is the union of TWO scans, because the working tree alone is not enough in a
worktree:

  1. the local glob -- this lane's tree, including issues not yet committed; and
  2. every `<PROJECT>-<n>-*.md` path that has ever appeared on ANY ref.

Worktrees share one object database and one `refs/` namespace -- only HEAD and the
index are per-worktree -- so scan 2 sees issue files committed on every other lane's
branch, which a worktree branched before them cannot see on disk. Without it, two
lanes branched from the same commit mint the same number (observed twice in one day
on the project this was extracted from, each time discovered only after the ID was
baked into the filename, body, links and prose).

Scan 2 walks paths ever TOUCHED, not a tree listing of current refs: a renamed-away
ID must stay RETIRED, or a renumber would free the old number and re-manufacture the
exact collision it escaped. `--no-renames` makes a rename list both sides whatever
the operator's `diff.renames` setting is.

Not airtight, and does not need to be: the residual window is two lanes minting
before either commits. Commit-then-mint is the common case.

Regenerates the local (gitignored) views afterwards.
"""
import argparse, datetime, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import backlog_index as bidx           # noqa: E402

ROOT = bidx.ROOT
ME = "me"   # --reported-by=me: this machine's operator short (LANES-2, /lanes:new)
BACKLOG = bidx.BACKLOG
BACKLOG_REL = bidx.BACKLOG_REL

BODY_STUB = """\
## Context

(What this is and why it exists. Overwrite to current understanding — history
lives in git blame + linked session assets, not in stacked amendments.)

## Current status

(Where it stands right now. Overwrite in place.)

## Resolution

(Fill on close: what settled it, with evidence / links.)
"""


def slugify(title, max_len=48):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rsplit("-", 1)[0]
    return s or "untitled"


def _issue_number(project, filename):
    """The <n> in `<PROJECT>-<n>-slug.md`, or None. One matcher for both scans."""
    m = re.match(rf"{re.escape(project)}-(\d+)\D", filename)
    return int(m.group(1)) if m else None


def local_max(project, backlog=None):
    """Highest ID for `project` in THIS working tree, committed or not.

    `backlog` overrides the module-level BACKLOG dir -- a caller may mint issues
    inside another worktree than the one the cwd is in.
    """
    n = 0
    for f in ((backlog or BACKLOG) / project).glob(f"{project}-*.md"):
        num = _issue_number(project, f.name)
        if num is not None:
            n = max(n, num)
    return n


def refs_max(project, repo=None):
    """Highest ID for `project` ever seen on ANY ref. 0 when git can't answer.

    `repo` is the checkout to ask (default: this clone). A worktree shares its
    refs with the main clone, so asking from either sees the same history.

    `--all` covers every other worktree's branch (shared refs/, shared object
    database). Every path ever touched counts, so an ID renumbered away stays
    retired rather than being handed out twice.
    `--no-renames` pins that: it lists both sides of a rename, independent of the
    operator's `diff.renames` config.

    Returns 0 rather than raising on any git failure. ID assignment must keep
    working on a plain checkout, on a machine with no venv, and outside a repo
    entirely; degrading to the local glob is the documented fallback.
    """
    try:
        proc = subprocess.run(
            ["git", "log", "--all", "--no-renames", "--name-only",
             "--pretty=format:", "--", f"{BACKLOG_REL}/{project}"],
            cwd=repo or ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    if proc.returncode != 0:
        return 0
    n = 0
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        num = _issue_number(project, line.rsplit("/", 1)[-1])
        if num is not None:
            n = max(n, num)
    return n


def next_number(project, backlog=None):
    """Next free ID: one past the highest this tree OR any ref has ever used."""
    seen = refs_max(project, _repo_of(backlog)) if backlog else refs_max(project)
    return max(local_max(project, backlog), seen) + 1


def _repo_of(backlog):
    """The repository a `backlog` dir belongs to: its toplevel, else the dir's grandparent."""
    return bidx.lc.repo_root(cwd=backlog) or Path(backlog).parent.parent


def format_frontmatter(meta):
    # `epic` is written only when set: an issue under no epic carries no `epic:` key.
    order = ("id", "project", "type", "status", "priority", "blocked_on",
             "assignee", "reported_by", "opened", "closed", "commit", "resolution",
             "links", "epic")
    lines = ["---"]
    for key in order:
        if key not in meta:
            continue
        v = meta[key]
        if v is None:
            lines.append(f"{key}: null")
        elif isinstance(v, list):
            lines.append(f"{key}: [{', '.join(v)}]")
        else:
            lines.append(f"{key}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _parse_dir(backlog):
    """Frontmatter of every issue under `backlog`, for the epic-parent check.

    Not `bidx.load_issues()`: that reads the module-level BACKLOG, and a caller
    may pass a different one. Same parser, so the two never disagree.
    """
    out = []
    for path in sorted(Path(backlog).glob("*/*.md")):
        meta, _ = bidx.parse_frontmatter(path.read_text(encoding="utf-8"))
        if meta:
            out.append(meta)
    return out


def create_issue(project, title, type_="story", priority="normal", assignee=None,
                 status="open", blocked_on=None, opened=None, closed=None,
                 commit=None, links=None, body=None,
                 regen_index=True, backlog=None, epic=None, reported_by=None,
                 resolution=None):
    """Write the issue file and return its Path. Raises on invalid enums.

    `assignee` defaults to the configured default (the solo operator, or the first
    operator who may edit code). `reported_by` is who first raised the issue --
    `claude` or an operator short -- distinct from `assignee`, who works it. The
    CLI REQUIRES it; it is optional here so a migration can leave it null.
    `resolution` is the how-it-closed value; null on anything not closed at mint.

    `commit` is the short hash of the change that RESOLVED the issue -- not the
    commit that edits the issue file to close it. OPTIONAL: a hash cited before
    the commit is on the main branch is rewritten by any rebase, so the
    load-bearing citation is the commit SUBJECT in the Resolution prose.

    `backlog` is the backlog directory to write into (default: this repo's).

    `epic` names the parent epic. Checked at mint time against the issues in
    `backlog`: the parent must exist and be `type: epic`, the same rule
    `backlog_index.py --check` enforces afterwards.
    """
    if assignee is None:
        assignee = bidx.DEFAULT_ASSIGNEE
    if project not in bidx.PROJECTS:
        raise ValueError(f"project {project!r} not in {bidx.PROJECTS}")
    if type_ not in bidx.TYPES:
        raise ValueError(f"type {type_!r} not in {bidx.TYPES}")
    if priority not in bidx.PRIORITIES:
        raise ValueError(f"priority {priority!r} not in {bidx.PRIORITIES}")
    if status not in bidx.STATUSES:
        raise ValueError(f"status {status!r} not in {bidx.STATUSES}")
    if assignee not in bidx.ASSIGNEES:
        raise ValueError(f"assignee {assignee!r} not in {'|'.join(bidx.ASSIGNEES)}")
    if reported_by is not None and reported_by not in bidx.REPORTERS:
        raise ValueError(f"reported_by {reported_by!r} not in {'|'.join(bidx.REPORTERS)}")
    if resolution is not None and resolution not in bidx.RESOLUTIONS:
        raise ValueError(f"resolution {resolution!r} not in {'|'.join(bidx.RESOLUTIONS)}")
    if epic:
        parents = {m.get("id"): m for m in _parse_dir(backlog or BACKLOG)}
        if epic not in parents:
            raise ValueError(f"epic {epic!r} names an issue that does not exist")
        if parents[epic].get("type") != "epic":
            raise ValueError(f"epic {epic!r} is a {parents[epic].get('type')!r}, not an epic")
    pdir = (backlog or BACKLOG) / project
    pdir.mkdir(parents=True, exist_ok=True)
    iid = f"{project}-{next_number(project, backlog)}"
    meta = {
        "id": iid, "project": project, "type": type_, "status": status,
        "priority": priority, "blocked_on": blocked_on, "assignee": assignee,
        "reported_by": reported_by, "opened": opened, "closed": closed,
        "commit": commit, "resolution": resolution, "links": links or [],
    }
    if epic:
        meta["epic"] = epic
    path = pdir / f"{iid}-{slugify(title)}.md"
    content = f"{format_frontmatter(meta)}\n\n# {iid} — {title}\n\n{body or BODY_STUB}"
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    if regen_index:
        bidx.regenerate()
    return path


def main(argv=None):
    use_utf8_console()
    # `--root` changes every vocabulary the parser below validates against, so it
    # is read first, on its own, and the module reconfigured before the real
    # parser is built.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--root", default=None)
    pre_args, _ = pre.parse_known_args(argv)
    if pre_args.root:
        bidx.configure(Path(pre_args.root).resolve())
        global ROOT, BACKLOG, BACKLOG_REL
        ROOT, BACKLOG, BACKLOG_REL = bidx.ROOT, bidx.BACKLOG, bidx.BACKLOG_REL
    ap = argparse.ArgumentParser(description="lanes backlog: mint a new issue")
    ap.add_argument("--root", default=None, help="repository to mint into (default: the one containing the cwd)")
    ap.add_argument("project", choices=bidx.PROJECTS)
    ap.add_argument("title")
    ap.add_argument("--type", dest="type_", choices=bidx.TYPES, default="story")
    ap.add_argument("--priority", choices=bidx.PRIORITIES, default="normal")
    ap.add_argument("--assignee", choices=bidx.ASSIGNEES, default=bidx.DEFAULT_ASSIGNEE,
                    help="who works it")
    ap.add_argument("--reported-by", dest="reported_by", choices=(*bidx.REPORTERS, ME), required=True,
                    help="who raised it — required, no default (a default would mis-attribute); "
                         f"`{ME}` is this machine's operator (what /lanes:new passes)")
    ap.add_argument("--resolution", choices=bidx.RESOLUTIONS, default=None,
                    help="how it closed; only with --status=closed")
    ap.add_argument("--status", choices=bidx.STATUSES, default="open")
    ap.add_argument("--blocked-on", default=None)
    ap.add_argument("--opened", default=None, help="YYYY-MM-DD (default today)")
    ap.add_argument("--links", default=None, help="comma-separated issue IDs")
    ap.add_argument("--epic", default=None, metavar="ID",
                    help="parent epic (an existing issue with type: epic)")
    args = ap.parse_args(argv)
    if args.reported_by == ME:
        # Explicit, never a default: the operator typed /lanes:new, so the reporter is the
        # operator row this machine resolves to. An unknown machine in a multi-operator
        # repo has no row to name, and guessing is the mis-attribution the rule exists for.
        if not (bidx.SOLO or bidx.MACHINE.get("known")):
            ap.error(f"--reported-by={ME}: this machine ({bidx.MACHINE['id']}) has no operator row "
                     f"to name — pass the reporter's short ({'|'.join(bidx.REPORTERS)})")
        args.reported_by = bidx.MACHINE["short"]

    path = create_issue(args.project, args.title, type_=args.type_,
                        priority=args.priority, assignee=args.assignee, status=args.status,
                        reported_by=args.reported_by, resolution=args.resolution,
                        blocked_on=args.blocked_on,
                        opened=args.opened or datetime.date.today().isoformat(),
                        links=[x.strip() for x in args.links.split(",")] if args.links else None,
                        epic=args.epic)
    print(f"created {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
