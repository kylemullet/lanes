"""Render the startup Brief (LANES-67).

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage:
  python3 lanes_brief.py [--critical TEXT ...] [--note TEXT ...] [--since REF] [--who SHORT] < status-lines

stdin carries every startup check's status lines (`<LEVEL> <name>: <detail>`, LANES-66). The
Brief comes out in one fixed order, a line each, and a line with nothing to say is left out:

  critical: N — <item> · <item>          always; `critical: none` when empty. Each CRITICAL
                                           status line, then each --critical item. Never a
                                           priority dump: a top-priority issue is not urgent
                                           by being one
  <each CUE line, then each line in another spelling, as written>
  due: <ID> <title> <MM-DD> (<countdown>)  overdue or due within DUE_DAYS
  lanes: N — <name> <head title> · …      every lane in flight, one line
  ⚠️ <note>                                each --note: a conflict, a stale claim, a stale issue
  branches: <branch> · …                   unlanded topic branches no claim names, minus
                                           `git.permanent_branches`
  landed: <ID> <title> · …                 issues cited by main-branch commits since --since
  health: …                                the fold's health line
  <N> live · <X> <top priority> · oldest <N>d   always

Why. The session wrote the Brief from prose at every startup: it drifted between sessions, put
the one line that must be read last, cited bare IDs, and spent most of its lines saying nothing
had changed (7 of 14 on one project's Brief). The session still supplies its judgment, and only
that: the --critical items (a stale claim to ask about, a landing to OK) and the --note lines
(two lanes expecting one file, a stale issue). Everything else is computed, so two runs on the
same state print the same text.

`--since` defaults to ORIG_HEAD, which the startup pull sets; LANES-68 will pass the tip the
last Brief read instead.
"""
from __future__ import annotations

import argparse, datetime, fnmatch, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import backlog_index as bidx           # noqa: E402
import status_lines                    # noqa: E402

DUE_DAYS = 7
TITLE_WIDTH = 48
SEP = " · "


def short_title(title: str) -> str:
    """A title's first clause (before ` — `), cut at TITLE_WIDTH."""
    head = (title or "").split(" — ", 1)[0].strip()
    return head if len(head) <= TITLE_WIDTH else head[:TITLE_WIDTH - 1].rstrip() + "…"


def _cited(it: dict) -> str:
    return f"{it['id']} {short_title(it.get('_title', ''))}".rstrip()


def _git(*args) -> str:
    proc = subprocess.run(["git", *args], cwd=str(bidx.ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def unlanded_branches(issues: list) -> list[str]:
    """Remote branches not merged into the main branch, minus the main branch itself, any
    branch a live claim names (its lane line covers it) and `git.permanent_branches`."""
    claimed = {(i.get("_marker") or {}).get("branch") for i in issues if i.get("status") == "in-progress"}
    out = []
    for raw in _git("branch", "-r", "--no-merged", f"origin/{bidx.MAIN_BRANCH}").splitlines():
        name = raw.strip()
        if not name.startswith("origin/") or " -> " in name:
            continue
        name = name[len("origin/"):]
        if name == bidx.MAIN_BRANCH or name in claimed:
            continue
        if any(fnmatch.fnmatchcase(name, pat) for pat in bidx.PERMANENT_BRANCHES):
            continue
        out.append(name)
    return sorted(out)


def landed_ids(since: str | None) -> list[str]:
    """Issue IDs cited by commits on HEAD since `since`, oldest first, skipping the backlog's
    own bookkeeping commits. Nothing when `since` does not resolve or is HEAD itself."""
    if not since or not _git("rev-parse", "-q", "--verify", f"{since}^{{commit}}"):
        return []
    id_re = re.compile(r"\b(?:" + "|".join(map(re.escape, bidx.PROJECTS)) + r")-\d+\b")
    out = []
    for subject in reversed(_git("log", "--format=%s", f"{since}..HEAD").splitlines()):
        if subject.startswith("docs(backlog)"):
            continue
        for iid in id_re.findall(subject):
            if iid not in out:
                out.append(iid)
    return out


def render(issues: list, status: list[str], *, who: str, critical=(), notes=(),
           branches=(), landed=(), today: datetime.date | None = None) -> list[str]:
    """The Brief's lines, in order. Pure: everything it reads is an argument."""
    today = today or datetime.date.today()
    by_id = {i["id"]: i for i in issues if i.get("id")}
    folded = status_lines.fold(status)
    health = [l for l in folded if l.startswith("health: ")]
    shown = [l for l in folded if not l.startswith("health: ")]
    crit_status = [l[len("CRITICAL "):] for l in shown if l.startswith("CRITICAL ")]
    rest = [l for l in shown if not l.startswith("CRITICAL ")]

    # Timely and urgent only, never a priority dump: a top-priority issue that has waited for
    # weeks is not news. Urgency is the checks' CRITICAL lines and the session's judgment.
    items = crit_status + list(critical)
    out = [f"critical: {len(items)} — {SEP.join(items)}" if items else "critical: none"]
    out += rest

    due = []
    for i in bidx.due_issues(issues):
        try:
            days = (datetime.date.fromisoformat(str(i["due"])) - today).days
        except ValueError:
            continue
        if days <= DUE_DAYS:
            due.append(f"{_cited(i)} {str(i['due'])[5:]} ({bidx.due_label(days)})")
    if due:
        out.append(f"due: {SEP.join(due)}")

    lanes = []
    here = (bidx.MACHINE or {}).get("id")
    for ln in bidx.lanes_in_flight(issues):
        lb = bidx.lane_label(ln)
        seg = f"{lb['name']} {short_title(ln['head'].get('_title', ''))}".rstrip()
        if lb["phase"]:
            seg += f" ({lb['phase']})"
        machine = str(lb.get("machine") or "").split("@", 1)[0]
        if machine and here and machine != here:
            seg += f" on {machine}"
        lanes.append(seg)
    if lanes:
        out.append(f"lanes: {len(lanes)} — {SEP.join(lanes)}")
    out += [f"⚠️ {n}" for n in notes]
    if branches:
        out.append(f"branches: {SEP.join(branches)}")
    if landed:
        out.append(f"landed: {SEP.join(_cited(by_id[x]) if x in by_id else x for x in landed)}")
    out += health

    mine = [i for i in issues if i.get("status") in bidx.LIVE_STATUSES
            and (who == "both" or i.get("assignee") in (who, bidx.lc.SHARED_ASSIGNEE))]
    top = bidx.PRIORITIES[0] if bidx.PRIORITIES else None
    ages = [a for a in (bidx._age(i.get("opened")) for i in mine if i.get("status") in ("open", "in-progress"))
            if a is not None]
    n_top = sum(1 for i in mine if i.get("priority") == top)
    out.append(f"{len(mine)} live · {n_top} {top or 'top priority'}" + (f" · oldest {max(ages)}d" if ages else ""))
    return out


def main(argv=None) -> int:
    use_utf8_console()
    use_utf8_console((sys.stdin,))
    ap = argparse.ArgumentParser(description="lanes: render the startup Brief from the backlog and the "
                                             "checks' status lines on stdin (LANES-67)")
    ap.add_argument("--critical", action="append", default=[], metavar="TEXT",
                    help="a judgment item for the critical line (repeatable)")
    ap.add_argument("--note", action="append", default=[], metavar="TEXT",
                    help="a judgment line shown after the lanes: a conflict, a stale claim (repeatable)")
    ap.add_argument("--since", default="ORIG_HEAD", metavar="REF",
                    help="what counts as landed: commits after REF (default ORIG_HEAD, set by the pull)")
    ap.add_argument("--who", default=None, help="the operator whose live issues the stat counts (default: "
                                                "this machine's; `both` for everyone)")
    ap.add_argument("--root", default=None, help="repository (default: the one containing the cwd)")
    args = ap.parse_args(argv)
    if args.root:
        bidx.configure(Path(args.root).resolve())
    issues, _problems = bidx.load_issues()
    status = [] if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read().splitlines()
    who = args.who or (bidx.MACHINE or {}).get("short") or "both"
    for line in render(issues, status, who=who, critical=args.critical, notes=args.note,
                       branches=unlanded_branches(issues), landed=landed_ids(args.since)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
