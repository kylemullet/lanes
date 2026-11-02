"""Split an issue into an epic and its children in one step (LANES-47).

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage:
  python3 backlog_split.py CORE-12 "parse the header" "write the table" --reported-by=me
  python3 backlog_split.py CORE-12 "…" "…" --reported-by=me --push      # main clone: commit + push, no OK
  python3 backlog_split.py CORE-12 "…" --reported-by=claude --push     # from a lane: children minted on main, parent's edit in the lane
  python3 backlog_split.py CORE-12 "…" --reported-by=claude --dry-run    # print the plan, write nothing

An issue bigger than one landing is split BEFORE its lane starts. Worked as one issue in
phases, it never closes: each lane lands a phase and sends it back to the queue with the
next one written into Current status, the history stacks there, and the rest of the work
cannot be claimed, prioritized or dated piece by piece. Splitting it by hand took a type
edit, one `backlog_new.py` call per child and a status edit; this does it at once, so the
split is the easy path.

What happens depends on the issue:

  open / blocked / paused   it becomes `type: epic` (it is the natural parent), each title
                            is minted as a child with `epic: <ID>`, and its Current status
                            gains one line naming the children.
  an epic                   the children are minted under it; the epic is not touched.
  claimed by THIS machine   the partial landing: the lane lands what it could and closes the
                            issue `done`, and the titles are the REMAINDER. A claimed issue
                            cannot become the epic (an epic is never claimed, and never
                            verified), so the remainder goes under the issue's own epic, or,
                            when it has none, under a NEW epic minted over it: the issue gets
                            `epic: <new>` and stays the lane's claim, closing as the epic's
                            first child. Nothing in its claim marker changes.

Refused: an issue that is verified or closed (file what is left with `backlog_new.py
--links <ID>`), one claimed by another machine, an unknown ID. A failure part-way restores
the issue and removes what was minted. Each child inherits the issue's project, priority
and assignee; its Context is a stub naming the parent, for the session to fill in.

`--push` commits every file by explicit path and pushes it under the OK-free guard
(`push_guard.py --ok-free`): a backlog-only push needs no OK. From the main clone on the
main branch, or from a lane worktree (LANES-76): there it mints the children — and the epic
wrapped over a claimed parent — into the MAIN CLONE and pushes from it, so their IDs are on
origin the moment they exist, while the claimed parent's own edit (its `epic:` line) is
written to the lane's copy and rides in the lane's resolving commit. The main clone off the
main branch is refused before anything is written.

A split in a lane worktree WITHOUT `--push` is refused (exit 1, nothing written): the
children would reach origin only when the lane lands, and until then their numbers are free
in every other checkout — the LANES-63 collision, on the split path. `--in-lane` is the
deliberate exception (no origin, children that must ride in this commit) and says so.
"""
import argparse, datetime, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import backlog_index as bidx           # noqa: E402
import backlog_new as bn               # noqa: E402
import push_guard                      # noqa: E402

LIVE_UNCLAIMED = ("open", "blocked", "paused")


class Refused(Exception):
    """A check failed; nothing was written."""


CHILD_BODY = """\
## Context

A child of [[{epic}]], split from [[{parent}]] by `backlog_split.py` (LANES-47){why}.
(What this piece covers — overwrite with the part of the parent's Context it carries.)

""" + bn.ACCEPTANCE_STUB + """
## Current status

Open, not started.

## Resolution

(Fill on close: what settled it, with evidence / links.)
"""

WRAP_BODY = """\
## Context

The epic over [[{parent}]] and the rest of its work, minted when a lane landed part of it
(`backlog_split.py`, LANES-47). [[{parent}]] closes `done` for what landed, as this epic's first
child; {children} carry what is left. [[{parent}]]'s Context is the original statement.

## Current status

Open: [[{parent}]] is in its lane; the rest is open.

## Resolution

(Fill on close: what settled it, with evidence / links.)
"""


def _id_of(path):
    """`CORE-13` from `.../CORE-13-some-slug.md`."""
    return "-".join(Path(path).name.split("-", 2)[:2])


def find(issue_id):
    """(path, text, meta) of the issue in this backlog, or Refused."""
    project = issue_id.rsplit("-", 1)[0]
    hits = sorted((bidx.BACKLOG / project).glob(f"{issue_id}-*.md")) if project in bidx.PROJECTS else []
    if len(hits) != 1:
        raise Refused(f"{issue_id}: {'no issue file' if not hits else f'{len(hits)} issue files'} "
                      f"under {bidx.BACKLOG_REL}/{project}/")
    text = hits[0].read_text(encoding="utf-8")
    meta, _ = bidx.parse_frontmatter(text)
    if not meta:
        raise Refused(f"{issue_id}: unparseable frontmatter")
    return hits[0], text, meta


def set_field(text, key, value):
    """`text` with frontmatter `key: value` -- replaced in place, else added before the close."""
    nl = "\r\n" if "\r\n" in text else "\n"
    head, sep, body = text[3:].partition(f"{nl}---{nl}")
    lines = head.split(nl)
    for i, line in enumerate(lines):
        if line.partition(":")[0].strip() == key:
            lines[i] = f"{key}: {value}"
            break
    else:
        lines.append(f"{key}: {value}")
    return "---" + nl.join(lines) + sep + body


def with_status_line(text, line):
    """`line` as the first paragraph of Current status; the rest is kept."""
    nl = "\r\n" if "\r\n" in text else "\n"
    section = f"{nl}## Current status{nl}"
    if section not in text:
        return text
    pre, _, post = text.partition(section)
    return pre + section + nl + line + nl + nl + post.lstrip("\r\n")


def mode_of(issue_id, meta, text):
    """`children` (an epic), `convert` (a live unclaimed issue) or `remainder` (this machine's claim)."""
    status = meta.get("status")
    if status in ("verified", "closed"):
        raise Refused(f"{issue_id}: is `{status}` — file what is left with "
                      f"`backlog_new.py … --links {issue_id}`")
    if meta.get("type") == "epic":
        return "children"
    if status in LIVE_UNCLAIMED:
        return "convert"
    if status == "in-progress":
        line = next((l for l in text.splitlines() if l.startswith("⏳ IN-PROGRESS")), "")
        author = push_guard.marker_author(line)
        if not author or not push_guard.is_mine(author, bidx.MACHINE):
            raise Refused(f"{issue_id}: claimed by another session — only the lane that holds it "
                          "files its remainder")
        return "remainder"
    raise Refused(f"{issue_id}: status `{status}` cannot be split")


def split(issue_id, titles, reported_by, type_="story", today=None, dry_run=False, fetch=True,
          parent_root=None):
    """Split `issue_id`. Returns (mode, epic ID, [child IDs], [rel paths written], [rel paths
    written in the lane]).

    `parent_root` (LANES-76): a lane worktree. Set when the children are minted into the main
    clone (`bidx.ROOT`) from a lane, so their IDs are on origin the moment they exist, while a
    claimed parent's edit — its `epic:` line, the remainder case — is written to the LANE's copy
    and rides in the lane's resolving commit. The last element names that file; it is empty
    everywhere else."""
    today = today or datetime.date.today().isoformat()
    if type_ == "epic":
        raise Refused("children are stories, bugs, chores… — not epics; split a child later if it needs one")
    if not titles:
        raise Refused("name at least one child title")
    path, text, meta = find(issue_id)
    mode = mode_of(issue_id, meta, text)
    lane_path = None
    if parent_root is not None and mode == "remainder":
        # The parent is this lane's claim: its copy in the lane may already carry the lane's
        # edits, and the main clone's copy must stay as the claim left it (the push guard
        # would refuse a rewrite of a marker anyway). Read and write the lane's copy.
        lane_path = Path(parent_root) / path.relative_to(bidx.ROOT)
        path, text = lane_path, lane_path.read_text(encoding="utf-8")
    project = meta.get("project") or issue_id.rsplit("-", 1)[0]
    title = bidx.issue_title(bidx.parse_frontmatter(text)[1], issue_id)
    common = dict(priority=meta.get("priority") or "normal", assignee=meta.get("assignee"),
                  reported_by=reported_by, opened=today, regen_index=False, backlog=bidx.BACKLOG)
    if common["assignee"] not in bidx.ASSIGNEES:
        common["assignee"] = None           # a retired or unknown assignee: the configured default
    wrap = mode == "remainder" and not meta.get("epic")
    epic = issue_id if mode in ("convert", "children") else meta.get("epic")
    why = {"convert": " before its lane started", "children": "",
           "remainder": ", the remainder of a partial landing"}[mode]

    if dry_run:
        n = bn.next_number(project, bidx.BACKLOG, fetch=fetch)
        ids = [f"{project}-{n + i}" for i in range(len(titles) + (1 if wrap else 0))]
        new_epic = ids.pop(0) if wrap else None
        return mode, new_epic or epic, ids, [], []

    written, created, original = [], [], text
    try:
        if mode == "convert":
            path.write_text(set_field(text, "type", "epic"), encoding="utf-8", newline="")
        if wrap:
            epic_path = bn.create_issue(project, f"EPIC — {title}", type_="epic", fetch=fetch,
                                        body=WRAP_BODY.format(parent=issue_id, children="its children"),
                                        **common)
            created.append(epic_path)
            epic = _id_of(epic_path)
            path.write_text(set_field(text, "epic", epic), encoding="utf-8", newline="")
            fetch = False
        ids = []
        for i, child in enumerate(titles):
            p = bn.create_issue(project, child, type_=type_, epic=epic, fetch=fetch and i == 0,
                                body=CHILD_BODY.format(epic=epic, parent=issue_id, why=why), **common)
            created.append(p)
            ids.append(_id_of(p))
        names = ", ".join(f"[[{i}]]" for i in ids)
        if mode == "convert":
            line = (f"Split {today} into {names} (`backlog_split.py`, LANES-47): an epic now, in "
                    "progress while any child is claimed; the children carry the work.")
            path.write_text(with_status_line(path.read_text(encoding="utf-8"), line),
                            encoding="utf-8", newline="")
        if wrap:
            bidx.lc.write_lf(epic_path, epic_path.read_text(encoding="utf-8").replace(
                "its children carry", f"{names} carry", 1))          # LF on Windows too (LANES-45)
    except Exception:
        path.write_text(original, encoding="utf-8", newline="")
        for p in created:
            p.unlink(missing_ok=True)
        raise
    lane_written = []
    if mode in ("convert",) or wrap:
        (lane_written if lane_path is not None else written).append(path)
    written.extend(created)
    return (mode, epic, ids, [p.relative_to(bidx.ROOT).as_posix() for p in written],
            [p.relative_to(parent_root).as_posix() for p in lane_written])


def main(argv=None):
    use_utf8_console()
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--root", default=None)
    pre_args, _ = pre.parse_known_args(argv)
    if pre_args.root:
        bidx.configure(Path(pre_args.root).resolve())
    ap = argparse.ArgumentParser(description="lanes backlog: split an issue into an epic and its children")
    ap.add_argument("--root", default=None, help="repository to split in (default: the one containing the cwd)")
    ap.add_argument("id", metavar="ID")
    ap.add_argument("titles", nargs="+", metavar="TITLE", help="one per child, in working order")
    ap.add_argument("--type", dest="type_", choices=[t for t in bidx.TYPES if t != "epic"], default="story",
                    help="the children's type")
    ap.add_argument("--reported-by", dest="reported_by", choices=(*bidx.REPORTERS, bn.ME), required=True,
                    help=f"who raised the children — required; `{bn.ME}` is this machine's operator")
    ap.add_argument("--no-fetch", dest="fetch", action="store_false",
                    help="number from the refs already fetched; skip `git fetch origin` (offline)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the IDs; write nothing")
    ap.add_argument("--push", action="store_true",
                    help="commit every file and push it under the OK-free guard; from a lane worktree, "
                         "mint the children into the main clone and push from there (LANES-76)")
    ap.add_argument("--in-lane", dest="in_lane", action="store_true",
                    help="split in this lane worktree anyway, without reserving the children's IDs on "
                         "origin (they ride in the lane's commit; another lane can land the same numbers first)")
    args = ap.parse_args(argv)
    where = push_guard.position(bidx.ROOT, bidx.MAIN_BRANCH)
    lane_root = None
    if args.push and where and where.startswith(push_guard.IN_WORKTREE):
        # A lane reserves its children's numbers by minting them on the main branch (LANES-76,
        # the LANES-63 shape): from a worktree, --push mints into the main clone this worktree
        # shares its refs with. A claimed parent's own edit stays in the lane (split()).
        lane_root = bidx.ROOT
        bidx.configure(Path(bidx.main_clone()).resolve())
        where = push_guard.position(bidx.ROOT, bidx.MAIN_BRANCH)
        print(f"--push from a lane: minting the children into the main clone {bidx.ROOT}; a claimed "
              "parent's edit stays in the lane (LANES-76)", file=sys.stderr)
    if args.push and not args.dry_run:
        if where:
            ap.error(f"--push: {where} — the children's IDs are reserved on the main branch, so the "
                     f"main clone must be on `{bidx.MAIN_BRANCH}`")
    elif where and where.startswith(push_guard.IN_WORKTREE) and not (args.in_lane or args.dry_run):
        print(f"refused: {where}. Children minted here reach origin only when the lane lands, so until "
              "then their numbers are free in every other checkout (LANES-76). Add --push: it mints "
              "them into the main clone and pushes under the OK-free guard, and a claimed parent's "
              "edit stays here to ride in the lane's commit. --in-lane splits here anyway.",
              file=sys.stderr)
        return 1
    elif where and where.startswith(push_guard.IN_WORKTREE) and not args.dry_run:
        print("in-lane split: these IDs are on no ref until the lane lands, and another lane can take "
              "them first (LANES-76)", file=sys.stderr)
    if args.reported_by == bn.ME:
        if not (bidx.SOLO or bidx.MACHINE.get("known")):
            ap.error(f"--reported-by={bn.ME}: this machine ({bidx.MACHINE['id']}) has no operator row "
                     f"to name — pass the reporter's short ({'|'.join(bidx.REPORTERS)})")
        args.reported_by = bidx.MACHINE["short"]
    issue_id = args.id.strip().upper()
    try:
        mode, epic, ids, rels, lane_rels = split(issue_id, args.titles, args.reported_by, type_=args.type_,
                                                 dry_run=args.dry_run, fetch=args.fetch,
                                                 parent_root=lane_root)
    except (Refused, ValueError) as e:
        print(f"NOT SPLIT — {e}. Nothing was written.", file=sys.stderr)
        return 1
    verb = "would " if args.dry_run else ""
    if mode == "convert":
        print(f"{verb}convert {issue_id} to an epic")
    elif mode == "remainder":
        print(f"{verb}file the remainder of {issue_id} under {epic}")
    for child, title in zip(ids, args.titles):
        print(f"{verb}mint {child} — {title} (epic: {epic})")
    if args.dry_run:
        return 0
    bidx.refresh_main_view()
    for rel in rels:
        print(f"wrote {rel}")
    for rel in lane_rels:
        print(f"wrote {rel} in the lane {lane_root} — it rides in the lane's resolving commit")
    if not args.push:
        return 0
    subject = (f"docs(backlog): split {issue_id} into {', '.join(ids)}" if mode != "remainder"
               else f"docs(backlog): file the remainder of {issue_id} as {', '.join(ids)}")
    err = push_guard.commit_paths(bidx.ROOT, rels, subject)
    if err:
        print(f"not committed — {err}; stage them by path", file=sys.stderr)
        return 2
    code, msg = push_guard.push(bidx.ROOT, push_guard.load_cfg(bidx.ROOT), push_guard.OK_FREE)
    if code == 0:
        print(f"committed and {msg}")
        return 0
    print(f"committed, not pushed — {msg}. It rides with the next push the operator OKs.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
