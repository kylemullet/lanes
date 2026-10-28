---
name: session-startup
description: Use at the start of a working session on any machine of a repo that runs the lanes protocol. Triggers include "GA", "good morning", "what's in the queue", "startup", "let's get started", "catch me up", or any session-opening signal. The startup sequence: pulls the main branch, identifies the operator and machine from the lanes config, runs the project's preflight, closes verified issues on the certifying machine, builds the exclusion set of in-flight claims, renders the Brief, asks what kind of session the operator wants — Critical, Deep Dive, Housekeeping or Ops, one menu for every operator — and which backlog project, in the same dialog (or reads either from the trigger, e.g. "GA housekeeping", "GA ui"), and offers 2–3 proposals for that mode and project — then STOPS and waits for the operator to name the work.
---

# Startup sequence

## Why this skill exists

Everything shared between sessions, operators and machines reaches the others through
the main branch. A session that starts on a stale clone reads yesterday's state,
re-answers settled questions and sets up merge conflicts at shutdown. Startup = sync
first, then orient the right person to the right queue, then **stop** — the brief is a
recommendation, never the start of work.

Every rule below that reads as counterintuitive has a date and a failure behind it:
[`references/incidents.md`](references/incidents.md). Read the incident before deciding
you are the exception.

## Step zero: the config

The protocol is the same everywhere; what it points at comes from
`.claude/lanes/config.toml` in the repo (every key optional; defaults = **solo mode**).
Read it once, up front:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_doctor.py
```

The `config` line names the mode and THIS machine's operator row: id, `short`, whether it
`certifies` (may land on the main branch and run the backfill) and whether it may edit
code. Hold those four facts for the whole session. In solo mode the machine certifies
and edits everything, and every two-operator step below is a no-op. In a multi-operator
repo an unknown `(user.name, platform)` pair resolves to **no permissions**: ask, do not
guess.

Then make sure the commit guard is in place. It is idempotent and prints one line:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" guard_commit.py --install
```

It writes a git `pre-commit` shim that refuses a commit putting non-main-direct paths on
the main branch, or any commit made in the main clone off it. Running it every session is
the per-clone setup step: a fresh clone is guarded after its first startup, and a plugin
update re-points the shim. `installed (unchanged)` is its `OK` status line, which folds into
`health:` (step 7). Anything else is a `CUE` line the Brief shows: re-pointed, `off`, another
tool's hook, `core.hooksPath`.

The same goes for the view hooks (LANES-11), which regenerate the bookmarked backlog view
after any pull, rebase or branch switch in the main clone:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" view_hooks.py --install
```

They chain after another tool's hooks (git-lfs writes two of the three). `installed
(unchanged)` and `off` (`backlog.view_mode = "serve"`) are `OK`; anything else is a `CUE`
line.

Keys this skill binds to: `git.main_branch`, `backlog.dir`, `backlog.view_mode`, `backlog.view_port`,
`tests.command`, `operators[]`, `lanes.code` / `lanes.code_owner`. Where this skill says
*main branch*, *the backlog*, *the test command*, read the config's value.

## Procedure

### 1. Identify the operator AND the machine

From step zero. A machine is a `(git user.name, platform)` pair, never the user name
alone — one person on two machines is two rows with two ids, and the rules that gate
writes (the backfill, landing) are **machine** gates, not person gates. The **operator**
determines which queue to surface; the **machine** determines which gates fire.

### 2. Pull FIRST — before reading any state

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_pull.py
```

It fetches and fast-forwards the main branch, rebasing any local commits on it, and it
**reads a dirty tree before refusing** (LANES-38). A repository can carry a directory that
is both git-tracked and mirrored by a file-sync client, and the mirror usually delivers a
landing's bytes before the next pull: every other machine then sees modified and untracked
files that are byte-identical to origin, and a plain `git pull --rebase` refuses on them.
The script reconciles those paths without writing a single file (a write would ripple back
through the mirror as a change), carries a new local file origin lacks (an uncommitted
session asset stays untracked, as a pull would leave it), and refuses only on paths that
genuinely differ, naming each one. Never substitute `git stash` for it: a stash deletes
the untracked files for a moment, and the mirror propagates that delete to every other
machine. (`incidents.md` → "The clone the mirror had already updated".)

Another machine may have landed since this one last synced; that is routine. If the pull
refuses, resolve the named paths WITH the operator before anything else — a session must
not proceed on a diverged clone. Note what came in: `git log ORIG_HEAD..HEAD --oneline`
(the script sets `ORIG_HEAD` as a pull would).

**Then check for unlanded branches from this machine:**

```bash
git fetch --prune && git branch -r --no-merged origin/<main_branch>
```

Under the branch policy, code waits on a branch until a certifying machine clears it, so
a branch pushed last session is live work, not litter. The Brief's `branches:` line lists
every one no claim names (step 7); what each is waiting on is a `--note`. A branch older
than a couple of sessions is a staleness candidate for step 6. A branch that is meant never
to land (a reference implementation, a project's own bot branches) goes in
`git.permanent_branches` once (fnmatch patterns, LANES-67), and is never reported again.

**Before reporting what a branch is waiting on, grep the backlog for it:**

```bash
grep -rn "<branch-name>" <backlog.dir> --include=*.md | grep -v INDEX.md
```

An old branch usually has a disposition already recorded on the main branch, and that
disposition — not the branch — is the current state.

⚠️ **Never report a branch's own session asset as the current state.** It describes the
moment the branch was written; every decision since lives on the main branch where the
asset cannot see it. (`incidents.md` → "The stale artifact on the branch".)

### 2x. Extension point: `.claude/lanes/preflight.md`

If the file exists, read it now and do what it says. This is where a project's local
steps live — data mirrors to sweep, a server to start, a long-running measurement to
launch, a scheduled check to offer — and they run here, right after the pull, so that
anything slow overlaps with the rest of startup. The protocol skill never carries them.

### 2d. Close verified issues — certifying machines only

**The backstop.** A lane landed through `lanes_land.py` closes its own issue on landing,
and `session-closeout` sweeps the rest, so on a healthy day this finds nothing. It runs
anyway: a lane landed by hand, a close that could not push, a session that ended early.
Run it and report the result; a backlog-only push needs no OK (the branch policy below),
so it is never offered as a question.

A worktree lane ends with its issue at `status: verified`, Resolution filled, `commit:`
null — the lane cannot know its resolving commit's hash (the close rides in that commit,
and the pre-push rebase rewrites it). Startup, which has just pulled, is where the hash
becomes knowable:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --backfill --dry-run    # what would close, and what can't
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --backfill --commit     # fill commit:, flip to closed, ONE commit by path
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --backfill --push       # the same, fetched first and pushed (see below)
```

For every `verified` issue it finds the resolving commit on HEAD by the exact subject the
Resolution cites in backticks, fills `commit:`, sets `status: closed` (+ `closed:` = the
resolving commit's date if the lane left it null), and — with `--commit` — stages ONLY
those issue files and commits `docs(backlog): close <IDs> — backfill resolving commit
hash`. `--commit` does not push: the commit rides to origin with the next push the
operator OKs. That is a `CUE` status line (step 7).

**`--push`** is `--commit` made safe for several certifying machines at once. It fetches and
fast-forwards first, so it closes only what origin still shows as verified. It pushes only
when the OK-free guard passes (`push_guard.py --ok-free`: everything ahead of origin under
`git.ok_free_paths`, no edit to another machine's claim); otherwise the commit stays local
for the operator's OK. On a rejected push it rebases and retries, never forces. The close is
deterministic (commit date, fixed 7-character hash), so two machines closing one issue
write identical files, and the second one's commit merges cleanly or drops out. Use it by default;
`--commit` is for a project that set `git.ok_free_paths = []` (every push waits for an OK).

Rules:

- **Gate: this machine's row `certifies`.** The script enforces it itself and refuses
  elsewhere. A non-certifying machine's brief lists verified issues as *awaiting the
  certifying operator's close* and leaves the files alone. Several certifying machines
  may each run it, concurrently included (LANES-6). The convergence above replaces the
  old single-writer rule.
- A verified issue the script SKIPS (exit 1, listed on stderr) is a real finding: its
  Resolution is the stub, or its cited subject is not on HEAD (the subject drifted from
  the actual commit, or the lane never pushed), or its resolving commit reached outside
  `backlog.docs_lane_prefixes` and the Resolution has no `Docs:` line, or it owes a line
  `backlog.required_lines` requires and does not carry it. Fix the Resolution by hand
  (cite the real subject exactly; write the `Docs:` or required line the lane owed) and
  re-run; never edit `commit:` by hand. The backfill refuses the undocumented case itself
  because it runs before step 5's `--check`, and a closed issue is never checked again.
- It sits right after the pull so everything downstream reads the post-close state.

### 3. Flag new content from the other operator (multi-operator only)

From the pulled commits and `git status --porcelain --untracked-files=all | grep '^??'`
(the unfiltered form — a pathspec glob silently matches nothing):

- **A new session asset from the OTHER operator** (`docs/session-assets/`)? Read it and
  skim the backlog issues the pull touched (`git log ORIG_HEAD..HEAD --stat --
  <backlog.dir>`). Their shutdown sequence should already have queued anything you must act on
  as issues, so surface those rather than re-digesting the asset. Vet technical claims;
  "parser-valid" ≠ verified.
- **Untracked shared text** — a new session asset, or project text the other machine has
  not seen? Surface it now; it MUST be committed no later than shutdown, and committing
  it immediately is fine.

Solo mode: nothing to do.

### 4. Read the state

In this order: the project's standing-context document (whatever `preflight.md` or the
project's CLAUDE.md names — scope guardrails, locked decisions, collaboration
mechanics); the backlog (step 5 reads it mechanically); the latest dated file in
`docs/session-assets/` — narrative that has not propagated into the backlog yet.

### 5. Build the queue — run the report

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py              # rebuild the main clone's gitignored views; prints the file:// path
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --report     # this machine's operator; --who <short>|both
```

**The view is a file the operator bookmarks** (`backlog.view_mode = "file"`, the default,
LANES-11): `<main clone>/<backlog.dir>/index.html`, the `file://` path the first command
prints. It always lives in the MAIN CLONE and renders the main clone's files, whichever
checkout runs the script. Nothing has to remember to regenerate it: every lanes script that
writes the backlog does (`backlog_new.py`, `lanes_claim.py`, `push_guard.py --add`, the
backfill, `--check`), and the view hooks do after any pull. Its header names the commit it
was rendered from and when, and says when the clone is behind origin, so a stale page
announces itself. `INDEX.md` and `index.html` are generated and must stay gitignored; the
scripts refresh them only where they are.

**`view_mode = "serve"`** keeps the INFRA-43 shape: start the served view, detached, if it
is not already up (`run_in_background`), from the MAIN CHECKOUT. It re-parses on every
request, so refreshing the page is the regeneration:

```bash
curl -s -m 2 http://127.0.0.1:<backlog.view_port>/ >/dev/null || sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --serve
```

**The view's link is the report's `Sortable backlog` section, on its own line.** It is the operator's
whole queue — sortable, filterable, linking into each issue file — and it carries the
weight of "let me see everything and overrule the lane". Do NOT pass `--open` unless
asked; a browser window stealing focus every session is noise.

The report is the mechanical half, and its `PROJECTS` block is the project question's menu
(step 8). Yours: staleness judgment (step 6), the report blocks (step 7), the lane (step 8).
Titles compress — **read the issue file body before acting on or recommending an item.**

Also sanity-check the tooling: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py
--check`. A frontmatter problem, an orphaned claim, a `commit:` hash that is not an
ancestor of HEAD, or a verified issue that is unresolvable or missing its `Docs:` line:
fix that first, by hand, in the issue file.

**Status vocabulary** (protocol, not config):

| Field | Values |
| :-- | :-- |
| `status` | `in-progress` (claimed — someone is working it in a named worktree) · `open` · `blocked` (waiting on `blocked_on`) · `paused` (held by design) · `verified` (landed, operator-verified, awaiting the backfill close) · `closed` |
| `priority` | from `backlog.priorities` — how much it matters, independent of status |
| `blocked_on` | free text or an issue ID — strictly "what is this waiting on", never "what this unblocks" |
| `due` | optional `YYYY-MM-DD` — the day the issue stops being movable (a deadline, a dated event); the views and the report open with the dated issues in calendar order. A date the operator would merely like to hit is priority, not `due` |

"This unblocks the other operator" is a *reason to prioritize*, not a blocker — it
belongs in the report's `Why now` column.

**An `in-progress` issue is a claim, and a claim is a wall.** It never appears in blocks
IV or V, and neither does anything that conflicts with it — step 5b builds that
exclusion set mechanically before any recommendation is written. If a claim looks stale,
surface it as a **question**, never a takeover: the issue file is left byte-for-byte
alone and the operator answers. 🚫 **A session never writes to another issue's claim**,
including to release, re-date or correct it.

**An epic is never claimed.** It reads `in-progress` in every view while any child is
claimed: derived, never written. So an epic showing in progress is not itself a wall.
Its claimed children are, and step 5b's exclusion set lists those, not the epic.

### 5b. In-flight lanes — build the exclusion set BEFORE choosing anything

`in-progress` is a claim. Whoever holds it — another session, the other operator, or a
lane *this operator's previous session* left waiting on a verdict — the recommendation
routes around it. This step is mechanical so that judgment cannot skip it:

```bash
grep -rln "^status: in-progress" <backlog.dir>
git worktree list
git branch -r --no-merged origin/<main_branch>
```

`lanes_doctor.py` already does this classification (its `claim <ID>` lines); run it or
do it by hand, but do it before anything else is chosen. For every hit, read the issue's
**Current status** ⏳ marker:

**Before reading the table, check the claim's AGE — it overrides every row:**

```bash
date "+%Y-%m-%d %H:%M"          # compare against the marker's timestamp
```

🛑 **A claim younger than ~15 minutes is NEVER a stale-claim candidate, whatever the
evidence says.** A lane that is setting up has no worktree and no branch commits yet, so
it presents *exactly* the evidence signature of an abandoned one, and no command can tell
them apart. Age can. (`incidents.md` → "113 seconds".)

| Marker says | Evidence | Lane state (goes in the Brief) |
| :-- | :-- | :-- |
| `ACTIVE LANE` on THIS machine | worktree present, or branch exists / has commits | live — *building* / *branch pushed, awaiting the verdict* / *verified, awaiting the landing OK* |
| `ACTIVE LANE` on ANOTHER machine | branch on origin (after the step-2 fetch) | live on that machine — name it (`on <machine>@<host>`); its worktree is invisible from here and is never evidence either way |
| `WORKTREE PENDING` | none needed | live — *claimed, setting up*; route around it exactly as for an ACTIVE lane |
| `RESERVED, NOT STARTED` | none needed | queued behind the named lane |
| `ACTIVE LANE` | claim ≥15 min old AND no worktree (this machine's lane only) AND no branch AND no commits | stale-claim candidate — a **question** in the Brief (to the owning machine's session when it is another machine), never a takeover |

All four qualifiers on the last row are load-bearing. Note that "no session" is **not
checkable by any command** and never contributed evidence. **The marker names its machine**
(`<Short>'s session on <machine id>@<host>`, LANES-7), and the worktree check applies only
when that is this machine: `git worktree list` is local, so for another machine's lane the
pushed branch is the ONLY evidence there is. `lanes_doctor.py` applies exactly this rule.

Then build the **exclusion set**: every `in-progress` ID, plus every not-closed issue that
**conflicts** with one — it touches a file in an ACTIVE marker's expected-files list, it
extends or depends on the same module that lane is changing, or the in-flight issue's own
file sequences it (*"queued behind"*). A bare `links:` entry is not a conflict by itself.

The proposals (step 8) are drawn from what is left, and nothing else, whatever the mode.
The Brief's `critical:` line may name an in-flight lane **only** when it needs a decision
from the operator right now (a verified branch awaiting the landing OK, a stale claim to
release) — pass it as a `--critical` item marked `🔒 in flight` (step 7) so it cannot be
mistaken for a pick. **The operator's own
lanes are not an exception** — a claim does not care whose it is. (`incidents.md` → "Our
own claims in block V".)

### 6. Staleness pass

Backlog entries outlive their own resolution. Check the urgent candidates and anything
older than ~14 days against the newest session assets and `git log --oneline -20`: has a
later commit already closed it, or cleared the gate it names? Mark those `⚠️` in the
report. Never silently drop one — if an item no longer reproduces, *correcting the issue
file IS the deliverable*, and it is a Housekeeping pick (`status: closed`, `resolution: wont-do`
or `done`, Resolution filled). Publish a correction the moment it is written, not with the
next OK'd push — it is a backlog-only commit:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" push_guard.py --ok-free --push --add <issue file> -m "docs(backlog): <ID> — <what was stale>"
```

### 7. Render the Brief and the view link

Two sections, every time, each under a plain header — `Brief`, then `Sortable backlog` —
with no numerals, and then the mode question (step 8).

**The status lines** (LANES-66). Every check that reports into the Brief, the protocol's
own and every `preflight.md` step, gives its result as one or more status lines in one
spelling:

```
<LEVEL> <name>: <detail>          LEVEL is OK, CUE or CRITICAL; the name has no colon
```

`OK` means nothing to read. `CUE` is worth a glance and is never a finding. `CRITICAL` also
goes on the `critical:` line, whatever mode the operator picks. A line in any other spelling
is shown in full, so an unmarked check is never folded out of sight.

The protocol's own checks print in their own words, so write their status lines from this
table. A result outside the `OK` column is a `CUE`, unless the `CRITICAL` column names it:

| Name | `OK` when it printed | `CRITICAL` when |
| :-- | :-- | :-- |
| `pull` (step 2) | up to date, or a fast-forward | it refused |
| `doctor` (step zero) | `0 warn, 0 fail` | any `fail` |
| `commit guard` (step zero) | `installed (unchanged)` | — |
| `view hooks` (step zero) | `installed (unchanged)` or `off` | — |
| `backfill` (step 2d) | nothing to close, or closed and pushed | it skips a verified issue |
| `backlog check` (step 5) | `--check` exits 0 | it names a problem |

A `preflight.md` step prints its own lines in this spelling; the contract is in the template
`/lanes:init` writes.

**Brief.** A script renders it (LANES-67); never write the Brief by hand. Pass every status
line, verbatim, on stdin, and your judgment as arguments:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_brief.py [--critical "<item>" …] [--note "<line>" …] <<'EOF'
<every status line, one per line>
EOF
```

It folds the status lines through `status_lines.py` (every `OK` check becomes one name on
the `health:` line) and prints the Brief in one fixed order, leaving out any line with
nothing to say:

| Line | What it carries |
| :-- | :-- |
| `critical: N — <item> · <item>` | **always** (`critical: none` when empty): every `CRITICAL` status line, then each `--critical` |
| the `CUE` lines, then any unmarked line | the fold, as written |
| `due: <ID> <title> <MM-DD> (<countdown>) · …` | every issue overdue or due within seven days |
| `lanes: N — <name> <title> · …` | every lane in flight (step 5b), one line |
| `⚠️ <note>` | each `--note` |
| `branches: …` | unlanded branches no claim names, minus `git.permanent_branches` (step 2) |
| `landed: <ID> <title> · …` | issues cited by commits since the pull (`--since`, default `ORIG_HEAD`) |
| `health: …` | the fold |
| `<N> live · <X> <top priority> · oldest <N>d` | **always**: the backlog stat |

Show its output under the `Brief` header exactly as printed, in a code block, and add
nothing to it. Every ID it cites carries its title.

**After the first Brief, only what changed** (LANES-68). Each run saves what it reported
inside the clone's git directory: per machine, shared by every worktree and session of the
clone, never tracked. The next run, from any session on this machine, says only what changed
since then. The `critical:` line, `due:`, the `--note` lines and the stat are always in full.
A `since <HH:MM>: …` line follows the status lines: what landed (`--since` defaults to the tip
the last Brief read), the issues opened and closed, the lanes started and ended, or `nothing
changed`. A `CUE` whose level has not moved folds into `health:` as unchanged, and a check
whose level moved shows once, an `OK` one marked `(was <LEVEL>)`. `lanes:` reads `N in flight,
unchanged` and `branches:` is left out while their sets are the same. `--full` renders the
whole Brief: when the operator asks for everything, or when a saved Brief is too old to
compare against usefully.

**Your judgment goes in as arguments, and only there.** `--critical` is for what is timely
and urgent and no check reports: something blocking someone (the other operator above all),
something needing a decision now (a verified branch awaiting the landing OK, a stale claim
to release — mark an in-flight lane `🔒`), something actively costing. Not a priority dump:
an issue is not urgent by having the top priority. **The critical line is in the Brief so
that no mode answer can hide it**: the operator who asks for Housekeeping still sees the red
row. `--note` carries a line the lanes need: two lanes expecting one file (step 5b), what a
lane is waiting on, a branch's disposition from step 2, step 6's `⚠️` staleness marks.

**Sortable backlog.** The view's link alone on its own line, immediately after the
Brief — the `file://` path the generator printed (the main clone's, never a worktree's), or
`http://127.0.0.1:<view_port>/` when `view_mode = "serve"`. Nothing else in the section.
It is the operator's escape hatch from every proposal below.

**There is no full-backlog table**, and no fixed Critical / Quick-wins / Lane sections
(LANES-24): the operator usually acts on one of them, so analysis spent on all three was
mostly spent on sections nobody read. Step 8 puts it into the one mode the operator wants.
(`incidents.md` → "The full table that oscillated".)

### 8. Ask the mode and the project, then propose 2–3

**One dialog, two questions** (LANES-64). Right after the `Sortable backlog` section, ask
with the question tool: the mode first, the project second, in ONE call. The tool takes
several questions at once, so the project costs a choice, not a round trip. Ask only what
the trigger has not already answered:

- A mode word answers the mode (`GA housekeeping`, `startup ops`).
- A project prefix answers the project, matched case-insensitively against
  `backlog.projects` (`GA deep dive CORE`). Named alone, it answers the mode too: Deep Dive,
  as an issue or epic ID does (`GA ui`, `GA LANES-12`).
- Critical answers the project as well: it never asks one.

When both are answered, ask nothing. When `backlog.projects` lists a single project, never
ask the project.

**The mode question.** These four options, in this order (the tool adds "Other").
The line under each option is quoted from this table verbatim: the menu the operator sees
and the rule the session follows are the same words, so they cannot drift.

| Option | Line under it |
| :-- | :-- |
| **Critical** | Urgent issues and blockers |
| **Deep Dive** | A single-context lane of issues, a project, or an epic. Research or spike. |
| **Housekeeping** | Issue-clearing, audits, and quick wins |
| **Ops** | Decisions, accounts, and outreach |

**One menu for every operator** (LANES-36). The split underneath it is who does the work:
Deep Dive and Housekeeping are what the session does and the operator verifies; Ops is
what the operator does, with the session preparing and recording. The order is also the
recommended default for a long session — what is on fire, then the big work while fresh,
then clearing, then what only the operator can do — so "whatever you think" proposes in
that order. An operator whose row does not edit code (`may_edit_code` false) gets the same
four options; their Deep Dive and Housekeeping proposals draw from docs-lane issues only
(`backlog.docs_lane_prefixes`), and a code change they need is queued as an issue for the
code owner. **Solo mode** gets the same menu.

"Other" takes free text: a project prefix, an epic ID, a theme. Treat it as Deep Dive
scoped to what they named.

**The project question.** Header `Project`, more than one answer allowed (a UI project with
its UX twin, a process project with its infrastructure). These options, in this order:

| Option | Line under it |
| :-- | :-- |
| **Any project** | Proposals from the whole backlog |
| the first row of the report's `PROJECTS` block | `<N> open · <M> active in the last 3 days` |
| its second row | the same |
| its third row | the same |

Step 5's `--report` ranks the projects mechanically: the ones with an issue opened, claimed
or closed in the last three days first, then the most open, and a project with nothing open
last. Take its first three rows with anything open; never re-rank them by judgment, or
the menu drifts from one session to the next. Fewer such rows means fewer options. "Other"
takes one or more prefixes, an epic ID, or a theme.

**The project narrows the proposals, never the Brief.** It filters step 5b's eligible set
before any proposal is drawn, in every mode but Critical, which ignores the project answer
because urgent work cuts across projects. The `critical:` line is already rendered above
the question, and no project answer removes an item from it. When the chosen projects have
nothing for the chosen mode, say so in one line and propose from the whole backlog.

**The proposals: 2–3, never one.** Each is a short table, so the operator chooses between
them rather than taking or overruling one. Every proposal is drawn only from step 5b's
eligible set — **no `in-progress` issue, nothing in the exclusion set, in any mode** — and,
outside Critical, only from the chosen projects. Every cited ID carries its IDENTICAL title. Sub-tasks within one issue are one row
(`CORE-2 · 2 sub-tasks`). When a lane is in flight, say each proposal is the *next* work
(*"after CORE-31 lands: …"*).

```
**A — <one-line thesis>**
| ID | Item | Why | Est | Blocked on |
First action: … · Parked: …
```

What each mode optimizes:

- **Critical** — the `critical:` items that are pickable, plus whatever blocks a lane, a
  person or a deploy. Urgency wins over the other three: an Ops item with a deadline is
  Critical. Proposals differ by which blocker they clear first.
- **Deep Dive** — the context-switching enemy: one project, or a machinery-sharing
  cluster in it, where ≥2 open issues touch the same files, so one context load closes
  several; or an epic's children in order. Research and spikes are Deep Dive too — a spike
  is a lane whose deliverable is a write-up. Proposals are alternative clusters.
- **Housekeeping** — issue-clearing, audits and quick wins: step 6's staleness
  corrections, qa issues, doctor warnings, a doc audit, the self-contained closes.
  Proposals are batches of 2–4 by shared context, each with an honest `Est` — an audit
  can run an hour, so never imply one sitting.
- **Ops** — decisions, accounts and outreach: the backlog's `decision` issues, sign-ups
  and credentials only the operator may hold, applications, emails and follow-ups,
  counsel items. The session lays out the options with a recommendation, drafts the
  text, and writes the ruling or the outcome into the issue; the operator acts.
  Proposals are 1–3 independent picks batched by context, with an honest `Est`
  (measured numbers where they exist, estimates labelled as estimates).

**Autonomous was retired** (LANES-36). Under step 8a's rule 4 a session never opens a
second issue while one waits on a verdict, and `git.land_requires_ok` makes every landing
wait, so an "autonomous lane" was always one issue and then a stall. Unattended
throughput is a protocol change — landing a class of issues on green without the per-lane
OK — not a menu option. An unattended suite run still needs the machine kept awake.

**Then STOP and wait.** A proposal is a recommendation, not an assignment — startup does
NOT begin work. End the message by asking which proposal (or what else) the operator
wants. Work begins only when they name it ("do B", "run A", "go"). Sole exception: a
staleness correction from step 6 is part of the report itself.

### 8a. How a lane is EXECUTED — read this before saying "on it"

A lane is a **queue, not a batch.** Four rules, in priority order:

1. **Anything that is not a backlog claim is worked in a worktree.** Not "code" —
   *anything*. The only writes that belong in the main checkout are the claim itself, the
   closing docs, and the startup and shutdown sequences' own writes.
2. **One issue at a time, sequentially.** A lane of three issues is three worktrees
   worked one after another. Finish, land or park, clean up, *then* start the next.
3. **Pull, then take the baseline, BEFORE each issue.** Every issue starts from a freshly
   pulled main branch with a known test-count baseline behind it — a measurement
   `preflight.md` supplies, or one `tests.command` run produces. Before *each* issue, not
   once at the top of the lane: otherwise issue #2 inherits issue #1's breakage and
   neither bisects.
4. **Never start a second issue while one is unresolved.** "Unresolved" includes *waiting
   on the operator's verdict*. The session waits or asks — it does not open a new front to
   stay busy.

**The check that makes rule 1 real**, before the first edit of any issue:

```bash
git rev-parse --show-toplevel    # must NOT be the main clone
git rev-parse --abbrev-ref HEAD  # must NOT be the main branch
```

If either fails, stop and make the worktree. The plugin's position-guard hook enforces
the same rule on the edit tools; it never sees a write made through Bash. The commit
guard catches that write when it is committed, not when it is made, so the two commands
stay.

**The reply to "go" states the order before starting:**

> The lane is CORE-64, UI-40, INFRA-31. Working them one at a time, each in its own worktree
> off a fresh main, baseline read before each. Starting CORE-64 in `../<repo>-core-64`; I
> will report before opening the next.

If the operator wants them parallel they will say so, and that means **one Claude Code
session per worktree** — never one session juggling several. (`incidents.md` → "The day
with no product work".)

### 8b. On the directive — claim, commit, PUSH, then hand off

"go", "run the lane", "do CORE-64", "work X then Y" — any directive naming one issue, a
group, or one of the proposals. This is the ONE write startup makes in the main checkout
after the brief, and it happens *before* the first worktree exists:

1. **Resolve the directive to an ordered ID list.** Re-run the step-5b grep: if any named
   ID is already `in-progress`, stop and say so — it may be another session's lane. 🚫 Do
   not release, re-date or edit that claim to clear the way, however stale it looks.
   **An issue bigger than one landing is split now, before its lane starts** — phases or
   parts in its text, independent deliverables, more than one session's work. Say so, and
   on the operator's yes run `backlog_split.py <ID> "<child>" … --reported-by=claude --push`
   (`/lanes:split`): the issue becomes the epic, the children are minted under it, and the
   lane claims the children in its place. An epic is never claimed.
2. **Claim every ID now, up front, in one call** — from the main checkout, on the main
   branch:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_claim.py <ID> [<ID> …] --files "<first ID's expected files>"
   ```

   It is steps 2–4 of the old hand procedure as one all-or-nothing operation (LANES-9). It
   fetches and fast-forwards; refuses unless **every** ID has a file on
   `origin/<main_branch>` (a missing one is named with the refs where it does exist, so a
   re-scope is the operator's decision, said out loud — never a silent swap); refuses an
   ID that is `in-progress`, `verified` or `closed`; writes frontmatter `status:
   in-progress` **and** the body marker on every ID — the first `WORKTREE PENDING` with its
   expected files, each later one `RESERVED, NOT STARTED` queued behind the one before it,
   LOCAL timestamps with minutes, spelled exactly as the doctor reads them; runs
   `backlog_index.py --check`; commits the issue files by explicit path; checks that
   everything ahead of origin matches `git.main_direct_paths`; and pushes, rebasing on a
   rejection and withdrawing the claim if another session changed one of those issues in
   the meantime. Exit `0` claimed and pushed · `1` nothing written · `2` committed but not
   pushed (the reason is printed — usually non-main-direct work on local main, which is
   to be surfaced, not pushed). `--dry-run` prints the markers; `--behind <ID>` adds IDs
   to the end of a lane already claimed instead of starting a new one, and `--next-in <ID>`
   to its front, as the next to work (LANES-49).

   **The directive IS the operator's OK for this push** — a claim exists to be seen, by a
   second session, the other operator, a second machine; a local-only claim protects
   only this machine. Other main-direct commits startup already made (the backfill, a
   staleness fix) ride along; the script's guard has checked every one of them.

   ⚠️ The marker says `WORKTREE PENDING`, not `ACTIVE LANE`, and names no worktree — it
   does not exist yet; `worktree-increment` step 2 flips it the moment `git worktree add`
   returns. Never hand-write a claim marker while the script is reachable: a hand-written
   one drifts from the spelling the doctor reads (`incidents.md` → "The lane claimed by
   hand").
3. Refresh the local views: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py`
   (the served view, if up, is already current).
4. If the script refused, report its line to the operator and stop; do not work around it.
5. **Hand off to `worktree-increment`** for the first ID.

## Lanes — who touches what (multi-operator only)

`lanes.code` names the paths only `lanes.code_owner`'s machine may edit; every other
operator queues a code change as an issue (`--assignee` the code owner's short) rather
than editing. Running the plugin's scripts is running, not editing — in-lane for
everyone. Backlog issues, session assets and the standing-context docs are dual-writer at
session boundaries; one file per issue means two operators rarely touch the same file,
and the generated views are gitignored so they cannot conflict. Solo mode: no lanes.

## Branch policy — where a session's work goes

- **Code** is worked on a named branch, never committed on the local main branch.
  Startup does not create one (it does not start work); it surfaces the branches in
  flight.
- **Docs, backlog issues and session assets are main-direct** (`git.main_direct_paths`)
  on every machine. Nothing in this skill's own writes goes on a branch.
- The operator-OK gate is on **landing on the main branch**, not on `git push`. Branch
  pushes are free; nothing that moves `origin/<main_branch>` happens without the OK —
  with two exceptions, each behind a mechanical guard (`push_guard.py`, LANES-5):
  - **the claim push (8b)** — the directive is the OK; every path ahead of origin must be
    main-direct (`--claim`);
  - **a backlog-only push** — the backfill close, a staleness fix, a released claim, an
    issue minted mid-session. No OK: every path ahead of origin must be under
    `git.ok_free_paths` (default: the backlog dir alone), `backlog_index.py --check` green,
    and no commit may edit a claim marker another machine wrote (`--ok-free`). The
    standing docs are main-direct but NOT ok-free: they change rules every session reads
    as ground truth, so they keep the OK. When the guard refuses, the commit stays local
    and rides with the next push the operator OKs; say so.

## What this skill is NOT

Not a state-repair tool — unexpected merge conflicts, unrecognized files, or a
force-push situation: stop and investigate with the operator.
