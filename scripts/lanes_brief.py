"""Render the startup Brief (LANES-67), and only what changed since the last one (LANES-68).

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage:
  python3 lanes_brief.py [--critical TEXT ...] [--note TEXT ...] [--since REF] [--who SHORT]
                         [--full] [--no-save] < status-lines

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

Since the last Brief (LANES-68). Every run saves what it reported to STATE_REL under the
clone's git directory: per clone, so per machine, shared by every worktree and session of it,
and never tracked. The next run reads it and says only what changed:

  critical: …                              always, in full
  <a CUE or unmarked line that is new or whose level moved; an OK line whose level moved,
   marked `(was <LEVEL>)`>
  since <HH:MM>: <what changed>            landed, opened, closed, lanes started and ended;
                                           `nothing changed` when nothing did
  due: …                                   always: the countdown moves every day
  lanes: N in flight, unchanged            or the full lanes line when the set changed
  ⚠️ <note>                                always: the session's judgment is this run's
  branches: …                              only when the set changed
  health: …, N cues unchanged (<names>) — …  an unchanged CUE folds in here
  <the stat>                               always

`--full` renders the whole Brief whatever was saved. A run with no saved Brief renders the whole
Brief too, and `--since` then defaults to ORIG_HEAD, which the startup pull sets.

The reply (LANES-70). stdout is the operator's reply exactly as it goes in: a `**Brief**` header
line (machine, time, the tip read), the lines above as Markdown bullets, the stat under them,
then `**Sortable backlog** — <link>` (the main clone's file:// path, or the served URL). stderr
carries one line to the session: none of this reaches the operator until it is pasted. A
session that ran the script read it as having shown the Brief, and asked the mode question
with the Brief still in a collapsed tool result: every startup after LANES-67, until this.

Markdown, never a code block (LANES-73). The first pasted Brief was a code block of fourteen
`·`-joined lines, 150–300 characters each: the chat pane wrapped every one two or three times
in a monospace face, the `due:` and `lanes:` lists ran into each other, titles were cut mid-word
and `health:` named every check it had folded away. Kyle: "it looks like absolute dog shit".
Bullets wrap at word boundaries with a hanging indent, so each item stays one visual unit:

  - 🔴 **Critical (N)** — <item>           or nested, one item per line, past INLINE_ITEMS
  - 🟡 **<name>** — <detail>               each CUE line; an unmarked line as written
  - 🕘 **Since HH:MM** — nothing changed   or nested: `landed …`, `opened …`, `lanes started …`
  - 📅 **Due this week** — a · b · c       nested past INLINE_ITEMS; so are lanes, branches, landed
  - 🔒 **Lanes (N)** — …
  - ⚠️ <note>                              one ⚠️, whether or not the session wrote it
  - ✅ **Health** — N ok, M cues unchanged (<names>)   counts only, never the OK names
  <the stat>

Titles are cut at a word boundary (TITLE_WIDTH), never mid-word. `render` still prints the plain
one-line spelling, which the tests and the saved Brief read; `markdown` is what the reply carries.

Why. The session wrote the Brief from prose at every startup: it drifted between sessions, put
the one line that must be read last, cited bare IDs, and spent most of its lines saying nothing
had changed (7 of 14 on one project's Brief). With four or five sessions open at once, every
startup re-reported the same landings, the same canary run and the same lanes; "since last
session" meant nothing. The session still supplies its judgment, and only that: the --critical
items (a stale claim to ask about, a landing to OK) and the --note lines (two lanes expecting
one file, a stale issue). Everything else is computed, so the same state prints the same text.
"""
from __future__ import annotations

import argparse, datetime, fnmatch, json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import backlog_index as bidx           # noqa: E402
import status_lines                    # noqa: E402

DUE_DAYS = 7
TITLE_WIDTH = 40
SINCE_ITEMS = 5          # per kind on the `since` line, then "+N more"
INLINE_ITEMS = 3         # a bullet joins at most this many items with SEP; more become a nested list
SEP = " · "
STATE_REL = Path("lanes") / "last-brief.json"    # under `git rev-parse --git-common-dir`
SHOW_IT = ("lanes: the operator has not seen this. Put everything above in your reply, as printed, "
           "before you ask the mode question: a tool result never reaches the operator (LANES-70).")


def short_title(title: str) -> str:
    """A title's first clause (before ` — `), cut at a word boundary within TITLE_WIDTH (LANES-73:
    a cut at a character count landed mid-word, `lanes_brie…`)."""
    head = (title or "").split(" — ", 1)[0].strip()
    if len(head) <= TITLE_WIDTH:
        return head
    window = head[:TITLE_WIDTH]
    cut = window.rsplit(" ", 1)[0] if " " in window else head[:TITLE_WIDTH - 1]
    cut = re.sub(r"\s*[(\[]\S*$", "", cut)        # never end on an opening bracket's word
    return cut.rstrip(" ,;:-–") + "…"


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


# --- the reply (LANES-70) -------------------------------------------------------------------

def view_link() -> str:
    """The `Sortable backlog` link: the served URL, or the main clone's file:// view, which
    is the one to bookmark whichever checkout runs this (LANES-11)."""
    if bidx.VIEW_MODE == "serve":
        return f"http://127.0.0.1:{bidx.VIEW_PORT}/"
    return (Path(bidx.main_clone()) / bidx.BACKLOG_REL / "index.html").as_uri()


def header(now: datetime.datetime, tip: str = "") -> str:
    """The Brief's first line: where and when it was rendered, and the tip it read."""
    parts = ["**Brief**", "—"]
    machine = (bidx.MACHINE or {}).get("id")
    if machine:
        parts += [machine, "·"]
    parts.append(now.strftime("%Y-%m-%d %H:%M"))
    if tip:
        parts += ["·", f"{bidx.MAIN_BRANCH} at {tip[:7]}"]
    return " ".join(parts)


def reply(brief_md: list[str], link: str, head: str = "**Brief**") -> list[str]:
    """The reply, ready to paste: the header, the Brief as Markdown bullets with the stat
    under them, then the `Sortable backlog` link on its own line (LANES-73: never a code
    block — the pane wraps a 200-character monospace line three times, and a wrapped
    `·`-joined list reads as prose)."""
    return [head, "", *brief_md, "", f"**Sortable backlog** — {link}"]


# --- the saved Brief (LANES-68) -------------------------------------------------------------

def state_path() -> Path | None:
    """Where this clone keeps its last Brief: inside the git directory every worktree of the
    clone shares, so it is per machine and can never be committed. None outside a repo."""
    common = _git("rev-parse", "--git-common-dir")
    if not common:
        return None
    path = Path(common)
    return (path if path.is_absolute() else Path(bidx.ROOT) / path) / STATE_REL


def load_state(path: Path | None) -> dict | None:
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("at") else None


def save_state(path: Path | None, state: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def snapshot(issues: list, status: list[str], *, branches=(), tip: str = "",
             now: datetime.datetime | None = None) -> dict:
    """What this Brief reported, as the next one compares it: each check's level by name,
    the lanes in flight, the live issues, every issue known, the unlanded branches, the tip."""
    now = now or datetime.datetime.now()
    checks = {}
    for line in status:
        parsed = status_lines.parse(line)
        if parsed:
            checks[parsed[1]] = parsed[0]
    return {"at": now.strftime("%Y-%m-%d %H:%M"), "tip": tip, "checks": checks,
            "lanes": [ln["key"] for ln in bidx.lanes_in_flight(issues)],
            "live": sorted(i["id"] for i in issues if i.get("status") in bidx.LIVE_STATUSES and i.get("id")),
            "known": sorted(i["id"] for i in issues if i.get("id")),
            "branches": list(branches)}


def _since_label(at: str, now: datetime.datetime) -> str:
    day, _, hm = at.partition(" ")
    return hm if day == now.strftime("%Y-%m-%d") else f"{day[5:]} {hm}"


def _capped(kind: str, cited: list[str]) -> str:
    more = f" +{len(cited) - SINCE_ITEMS} more" if len(cited) > SINCE_ITEMS else ""
    return f"{kind} {SEP.join(cited[:SINCE_ITEMS])}{more}"


def _lane_segment(ln: dict, here: str | None) -> str:
    lb = bidx.lane_label(ln)
    seg = f"{lb['name']} {short_title(ln['head'].get('_title', ''))}".rstrip()
    if lb["phase"]:
        seg += f" ({lb['phase']})"
    machine = str(lb.get("machine") or "").split("@", 1)[0]
    if machine and here and machine != here:
        seg += f" on {machine}"
    return seg


# --- the Brief ------------------------------------------------------------------------------

def assemble(issues: list, status: list[str], *, who: str, critical=(), notes=(),
             branches=(), landed=(), today: datetime.date | None = None,
             last: dict | None = None, now: datetime.datetime | None = None) -> list[tuple]:
    """The Brief's parts, in order — `(kind, payload)` pairs that `render` prints as plain
    lines and `markdown` as bullets: the whole Brief, or with `last` (a saved snapshot) only
    what changed since it. Pure: everything it reads is an argument."""
    now = now or datetime.datetime.now()
    today = today or now.date()
    by_id = {i["id"]: i for i in issues if i.get("id")}
    folded = status_lines.fold(status)
    shown = [l for l in folded if not l.startswith("health: ")]
    crit_status = [l[len("CRITICAL "):] for l in shown if l.startswith("CRITICAL ")]
    rest = [l for l in shown if not l.startswith("CRITICAL ")]
    ok = list(dict.fromkeys(p[1] for p in map(status_lines.parse, status) if p and p[0] == "OK"))

    # Timely and urgent only, never a priority dump: a top-priority issue that has waited for
    # weeks is not news. Urgency is the checks' CRITICAL lines and the session's judgment.
    out = [("critical", crit_status + list(critical))]

    then = (last or {}).get("checks", {})
    unchanged = []
    if last is None:
        out += [("status", l) for l in rest]
    else:
        for line in rest:                    # a CUE that has not moved is not news
            parsed = status_lines.parse(line)
            if parsed and then.get(parsed[1]) == parsed[0]:
                unchanged.append(parsed[1])
            else:
                out.append(("status", line))
        for line in status:                  # a check that came back to OK says so once
            parsed = status_lines.parse(line)
            if parsed and parsed[0] == "OK" and then.get(parsed[1]) not in (None, "OK"):
                out.append(("status", f"{line.strip()} (was {then[parsed[1]]})"))

        changed = []
        if landed:
            changed.append(("landed", [_cited(by_id[x]) if x in by_id else x for x in landed]))
        known, live_then = set(last.get("known", [])), set(last.get("live", []))
        # A new issue already claimed is told once, as the lane it started.
        opened = sorted((i for i in issues if i.get("id") and i["id"] not in known
                         and i.get("status") in bidx.LIVE_STATUSES and i.get("status") != "in-progress"),
                        key=bidx.sort_key)
        if opened:
            changed.append(("opened", [_cited(i) for i in opened]))
        closed = sorted((i for i in issues if i.get("id") in live_then and i["id"] not in landed
                         and i.get("status") in ("verified", "closed")), key=bidx.sort_key)
        if closed:
            changed.append(("closed", [_cited(i) for i in closed]))
        lanes_now = {ln["key"]: ln for ln in bidx.lanes_in_flight(issues)}
        here = (bidx.MACHINE or {}).get("id")
        started = [k for k in lanes_now if k not in last.get("lanes", [])]
        ended = [k for k in last.get("lanes", []) if k not in lanes_now]
        if started:
            changed.append(("lanes started", [_lane_segment(lanes_now[k], here) for k in started]))
        if ended:
            lead = [k.split("@", 1)[0] for k in ended]
            changed.append(("lanes ended", [_cited(by_id[x]) if x in by_id else x for x in lead]))
        out.append(("since", (_since_label(last["at"], now), changed)))

    due = []
    for i in bidx.due_issues(issues):
        try:
            days = (datetime.date.fromisoformat(str(i["due"])) - today).days
        except ValueError:
            continue
        if days <= DUE_DAYS:
            due.append(f"{_cited(i)} {str(i['due'])[5:]} ({bidx.due_label(days)})")
    if due:
        out.append(("due", due))

    here = (bidx.MACHINE or {}).get("id")
    lanes = bidx.lanes_in_flight(issues)
    if last is not None and lanes and [ln["key"] for ln in lanes] == list(last.get("lanes", [])):
        out.append(("lanes unchanged", len(lanes)))
    elif lanes:
        out.append(("lanes", [_lane_segment(ln, here) for ln in lanes]))
    out += [("note", n) for n in notes]
    if branches and (last is None or list(branches) != list(last.get("branches", []))):
        out.append(("branches", list(branches)))
    if landed and last is None:
        out.append(("landed", [_cited(by_id[x]) if x in by_id else x for x in landed]))
    if ok or unchanged:
        out.append(("health", (len(ok), unchanged)))

    mine = [i for i in issues if i.get("status") in bidx.LIVE_STATUSES
            and (who == "both" or i.get("assignee") in (who, bidx.lc.SHARED_ASSIGNEE))]
    top = bidx.PRIORITIES[0] if bidx.PRIORITIES else None
    ages = [a for a in (bidx._age(i.get("opened")) for i in mine if i.get("status") in ("open", "in-progress"))
            if a is not None]
    n_top = sum(1 for i in mine if i.get("priority") == top)
    out.append(("stat", f"{len(mine)} live · {n_top} {top or 'top priority'}" + (f" · oldest {max(ages)}d" if ages else "")))
    return out


def _note(text: str) -> str:
    """A note carries one ⚠️, whether or not the session already wrote it (LANES-73)."""
    return text if text.startswith("⚠️") else f"⚠️ {text}"


def _health(n_ok: int, unchanged: list[str]) -> str:
    """Counts only. The OK checks were folded so there was nothing to read; naming eleven of
    them on the fold line put it back (LANES-73)."""
    text = f"{n_ok} ok"
    if unchanged:
        text += f", {len(unchanged)} cue{'s' if len(unchanged) > 1 else ''} unchanged ({', '.join(unchanged)})"
    return text


def _plain(kind: str, payload) -> str:
    """One part as a plain line: the spelling `render` keeps, which the tests and the saved
    Brief read."""
    if kind == "critical":
        return f"critical: {len(payload)} — {SEP.join(payload)}" if payload else "critical: none"
    if kind in ("status", "stat"):
        return payload
    if kind == "since":
        label, changed = payload
        return f"since {label}: " + ("; ".join(_capped(k, c) for k, c in changed) or "nothing changed")
    if kind == "lanes unchanged":
        return f"lanes: {payload} in flight, unchanged"
    if kind == "lanes":
        return f"lanes: {len(payload)} — {SEP.join(payload)}"
    if kind == "note":
        return _note(payload)
    if kind == "health":
        return f"health: {_health(*payload)}"
    return f"{kind}: {SEP.join(payload)}"          # due, branches, landed


def render(issues: list, status: list[str], **kw) -> list[str]:
    """The Brief's plain lines, in order (see `assemble`)."""
    return [_plain(kind, payload) for kind, payload in assemble(issues, status, **kw)]


# --- the Brief as Markdown (LANES-73) -------------------------------------------------------

ICONS = {"critical": "🔴", "due": "📅", "lanes": "🔒", "since": "🕘", "branches": "🌿",
         "landed": "📦", "health": "✅", "cue": "🟡", "ok": "✅"}


def _bullet(icon: str, label: str, items: list[str], depth: int = 0) -> list[str]:
    """One bullet, its items inline when there are at most INLINE_ITEMS, else nested one
    level: the pane wraps a long line, and a wrapped `·`-joined list reads as prose."""
    pad = "  " * depth
    head = f"{pad}- {icon} **{label}**".rstrip()
    if not items:
        return [head]
    if len(items) <= INLINE_ITEMS:
        return [f"{head} — {SEP.join(items)}"]
    return [head] + [f"{pad}  - {it}" for it in items]


def _since_md(label: str, changed: list[tuple[str, list[str]]]) -> list[str]:
    if not changed:
        return [f"- {ICONS['since']} **Since {label}** — nothing changed"]
    out = [f"- {ICONS['since']} **Since {label}**"]
    for kind, cited in changed:
        shown = cited[:SINCE_ITEMS]
        more = [f"+{len(cited) - SINCE_ITEMS} more"] if len(cited) > SINCE_ITEMS else []
        if len(shown) + len(more) <= INLINE_ITEMS:
            out.append(f"  - {kind} {SEP.join(shown + more)}")
        else:
            out.append(f"  - {kind} ({len(cited)})")
            out += [f"    - {c}" for c in shown + more]
    return out


def _status_md(line: str) -> str:
    parsed = status_lines.parse(line)
    if parsed is None:                        # an unmarked check: shown in full, as written
        return f"- {line}"
    level, name, detail = parsed
    icon = ICONS["cue"] if level == "CUE" else ICONS["ok"] if level == "OK" else ICONS["critical"]
    return f"- {icon} **{name}** — {detail}"


def markdown(parts: list[tuple]) -> list[str]:
    """The Brief as Markdown bullets, the stat on its own line under them: what the reply
    carries. One item per bullet; `due`, `lanes`, `branches` and `landed` nest past
    INLINE_ITEMS; `health` is counts only; a note carries one ⚠️."""
    out = []
    for kind, payload in parts:
        if kind == "critical":
            out += (_bullet(ICONS["critical"], f"Critical ({len(payload)})", payload) if payload
                    else [f"- 🟢 **Critical** — none"])
        elif kind == "status":
            out.append(_status_md(payload))
        elif kind == "since":
            out += _since_md(*payload)
        elif kind == "due":
            out += _bullet(ICONS["due"], "Due this week", payload)
        elif kind == "lanes unchanged":
            out.append(f"- {ICONS['lanes']} **Lanes ({payload})** — in flight, unchanged")
        elif kind == "lanes":
            out += _bullet(ICONS["lanes"], f"Lanes ({len(payload)})", payload)
        elif kind == "note":
            out.append(f"- {_note(payload)}")
        elif kind == "branches":
            out += _bullet(ICONS["branches"], "Branches", payload)
        elif kind == "landed":
            out += _bullet(ICONS["landed"], "Landed", payload)
        elif kind == "health":
            out.append(f"- {ICONS['health']} **Health** — {_health(*payload)}")
        elif kind == "stat":
            out += ["", payload]
    return out


def main(argv=None) -> int:
    use_utf8_console()
    use_utf8_console((sys.stdin,))
    ap = argparse.ArgumentParser(description="lanes: render the startup Brief from the backlog and the "
                                             "checks' status lines on stdin (LANES-67), and only what "
                                             "changed since the last one on this clone (LANES-68)")
    ap.add_argument("--critical", action="append", default=[], metavar="TEXT",
                    help="a judgment item for the critical line (repeatable)")
    ap.add_argument("--note", action="append", default=[], metavar="TEXT",
                    help="a judgment line shown after the lanes: a conflict, a stale claim (repeatable)")
    ap.add_argument("--since", default=None, metavar="REF",
                    help="what counts as landed: commits after REF (default: the tip the last Brief read, "
                         "else ORIG_HEAD, which the pull sets)")
    ap.add_argument("--full", action="store_true", help="the whole Brief, whatever the last one said")
    ap.add_argument("--no-save", action="store_true", help="do not record this Brief as the last one")
    ap.add_argument("--who", default=None, help="the operator whose live issues the stat counts (default: "
                                                "this machine's; `both` for everyone)")
    ap.add_argument("--root", default=None, help="repository (default: the one containing the cwd)")
    args = ap.parse_args(argv)
    if args.root:
        bidx.configure(Path(args.root).resolve())
    issues, _problems = bidx.load_issues()
    status = [] if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read().splitlines()
    who = args.who or (bidx.MACHINE or {}).get("short") or "both"
    path = state_path()
    last = None if args.full else load_state(path)
    since = args.since
    if since is None:
        tip = (last or {}).get("tip")
        # The last Brief's tip, while it is still on this branch's history (a rewrite drops it).
        reachable = tip and subprocess.run(["git", "merge-base", "--is-ancestor", tip, "HEAD"],
                                           cwd=str(bidx.ROOT), capture_output=True).returncode == 0
        since = tip if reachable else "ORIG_HEAD"
    branches = unlanded_branches(issues)
    now = datetime.datetime.now()
    tip = _git("rev-parse", "HEAD")
    parts = assemble(issues, status, who=who, critical=args.critical, notes=args.note,
                     branches=branches, landed=landed_ids(since), last=last, now=now)
    for line in reply(markdown(parts), view_link(), header(now, tip)):
        print(line)
    sys.stdout.flush()
    print(SHOW_IT, file=sys.stderr)
    if not args.no_save:
        save_state(path, snapshot(issues, status, branches=branches, tip=tip, now=now))
    return 0


if __name__ == "__main__":
    sys.exit(main())
