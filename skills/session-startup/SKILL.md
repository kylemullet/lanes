---
name: session-startup
description: Use at the start of a working session on any machine of a repo that runs the lanes protocol. Triggers include "GA", "good morning", "what's in the queue", "startup", "let's get started", "catch me up", or any session-opening signal. Pulls the main branch, identifies the operator and machine from the lanes config, runs the project's preflight, closes verified issues on the certifying machine, builds the exclusion set of in-flight claims, renders the Brief, asks what kind of session the operator wants — Critical, Deep Dive, Housekeeping or Ops, one menu for every operator (or reads it from the trigger, e.g. "GA housekeeping"), and offers 2–3 proposals for that mode — then STOPS and waits for the operator to name the work.
---

# Session startup

## Why this skill exists

Everything shared between sessions, operators and machines reaches the others through
the main branch. A session that starts on a stale clone reads yesterday's state,
re-answers settled questions and sets up merge conflicts at closeout. Startup = sync
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
update re-points the shim. `installed (unchanged)` needs no Brief line. Anything else goes
in the Brief: re-pointed, `off`, another tool's hook, `core.hooksPath`.

The same goes for the view hooks (LANES-11), which regenerate the bookmarked backlog view
after any pull, rebase or branch switch in the main clone:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" view_hooks.py --install
```

They chain after another tool's hooks (git-lfs writes two of the three). `installed
(unchanged)` and `off` (`backlog.view_mode = "serve"`) need no Brief line; anything else
does.

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
git pull --rebase
```

Another machine may have landed since this one last synced; that is routine. If the pull
conflicts, resolve it WITH the operator before anything else — a session must not
proceed on a diverged clone. Note what came in: `git log ORIG_HEAD..HEAD --oneline`.

**Then check for unlanded branches from this machine:**

```bash
git fetch --prune && git branch -r --no-merged origin/<main_branch>
```

Under the branch policy, code waits on a branch until a certifying machine clears it, so
a branch pushed last session is live work, not litter. Surface any this operator owns,
with what each is waiting on. A branch older than a couple of sessions is a staleness
candidate for step 6.

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
operator OKs. Mention it in the Brief.

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
  `backlog.docs_lane_prefixes` and the Resolution has no `Docs:` line. Fix the Resolution
  by hand (cite the real subject exactly; write the `Docs:` line the lane owed) and
  re-run; never edit `commit:` by hand. The backfill refuses the undocumented case itself
  because it runs before step 5's `--check`, and a closed issue is never checked again.
- It sits right after the pull so everything downstream reads the post-close state.

### 3. Flag new content from the other operator (multi-operator only)

From the pulled commits and `git status --porcelain --untracked-files=all | grep '^??'`
(the unfiltered form — a pathspec glob silently matches nothing):

- **A new session asset from the OTHER operator** (`docs/session-assets/`)? Read it and
  skim the backlog issues the pull touched (`git log ORIG_HEAD..HEAD --stat --
  <backlog.dir>`). Their closeout should already have queued anything you must act on
  as issues, so surface those rather than re-digesting the asset. Vet technical claims;
  "parser-valid" ≠ verified.
- **Untracked shared text** — a new session asset, or project text the other machine has
  not seen? Surface it now; it MUST be committed no later than closeout, and committing
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
weight of "let me see everything and overrule the slice". Do NOT pass `--open` unless
asked; a browser window stealing focus every session is noise.

The report is the mechanical half. Yours: staleness judgment (step 6), the report blocks
(step 7), the slice (step 8). Titles compress — **read the issue file body before acting
on or recommending an item.**

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
release) — mark it `🔒 in flight` so it cannot be mistaken for a pick. **The operator's own
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
with no numerals, and then the mode question (step 8). Keep item text to a short noun
phrase.

**Brief.** Bullets, one line each: sync result; what landed since last session;
anything needing a decision right now; the backfill result ("closed N verified: IDs —
commit pending push" / "N verified awaiting the certifying machine's close"); whatever
`preflight.md` asked to report; unlanded branches from step 2; **the in-flight lanes from
step 5b — one line per LANE, as `--report`'s IN PROGRESS block groups them: the slice name
(`LANES-20/21/9`), each issue's ACTIVE/PENDING/RESERVED state, lane state, what it is
waiting on**; the backlog stat (`N open · X critical · oldest Nd`); and, **always, the
critical line**:

```
critical: N — <ID> <noun phrase>, <ID> <noun phrase>, …        (or `critical: none`)
```

Timely and urgent only: a red canary row, something blocking someone (the other operator
above all), something needing a decision now, something actively costing. Not a priority
dump. **It is in the Brief so that no mode answer can hide it**: the operator who asks for
Housekeeping still sees the red row. Step 6's `⚠️` staleness marks ride on whatever line
cites the issue.

**Sortable backlog.** The view's link alone on its own line, immediately after the
Brief — the `file://` path the generator printed (the main clone's, never a worktree's), or
`http://127.0.0.1:<view_port>/` when `view_mode = "serve"`. Nothing else in the section.
It is the operator's escape hatch from every proposal below.

**There is no full-backlog table**, and no fixed Critical / Quick-wins / Slice sections
(LANES-24): the operator usually acts on one of them, so analysis spent on all three was
mostly spent on sections nobody read. Step 8 puts it into the one mode the operator wants.
(`incidents.md` → "The full table that oscillated".)

### 8. Ask the mode, then propose 2–3

**The mode question.** Skip it when the trigger already names a mode (`GA housekeeping`,
`startup ops`, `GA LANES-12`). Otherwise ask with the question tool, right after the
`Sortable backlog` section, with these four options in this order (the tool adds "Other").
The line under each option is quoted from this table verbatim: the menu the operator sees
and the rule the session follows are the same words, so they cannot drift.

| Option | Line under it |
| :-- | :-- |
| **Critical** | Urgent issues and blockers |
| **Deep Dive** | A single-context slice, project, or epic. Research or spike. |
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

**The proposals: 2–3, never one.** Each is a short table, so the operator chooses between
them rather than taking or overruling one. Every proposal is drawn only from step 5b's
eligible set — **no `in-progress` issue, nothing in the exclusion set, in any mode** — and
every cited ID carries its IDENTICAL title. Sub-tasks within one issue are one row
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
wait, so an "autonomous slice" was always one lane and then a stall. Unattended
throughput is a protocol change — landing a class of issues on green without the per-lane
OK — not a menu option. An unattended suite run still needs the machine kept awake.

**Then STOP and wait.** A proposal is a recommendation, not an assignment — startup does
NOT begin work. End the message by asking which proposal (or what else) the operator
wants. Work begins only when they name it ("do B", "run A", "go"). Sole exception: a
staleness correction from step 6 is part of the report itself.

### 8a. How a slice is EXECUTED — read this before saying "on it"

A slice is a **queue, not a batch.** Four rules, in priority order:

1. **Anything that is not a backlog claim is worked in a worktree.** Not "code" —
   *anything*. The only writes that belong in the main checkout are the claim itself, the
   closing docs, and the startup/closeout skills' own writes.
2. **One issue at a time, sequentially.** A slice of three issues is three worktrees
   worked one after another. Finish, land or park, clean up, *then* start the next.
3. **Pull, then take the baseline, BEFORE each issue.** Every issue starts from a freshly
   pulled main branch with a known test-count baseline behind it — a measurement
   `preflight.md` supplies, or one `tests.command` run produces. Before *each* issue, not
   once at the top of the slice: otherwise issue #2 inherits issue #1's breakage and
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

> Slice is CORE-64, UI-40, INFRA-31. Working them one at a time, each in its own worktree
> off a fresh main, baseline read before each. Starting CORE-64 in `../<repo>-core-64`; I
> will report before opening the next.

If the operator wants them parallel they will say so, and that means **one Claude Code
session per worktree** — never one session juggling several. (`incidents.md` → "The day
with no product work".)

### 8b. On the directive — claim, commit, PUSH, then hand off

"go", "run the slice", "do CORE-64", "work X then Y" — any directive naming one issue, a
group, or one of the proposals. This is the ONE write startup makes in the main checkout
after the brief, and it happens *before* the first worktree exists:

1. **Resolve the directive to an ordered ID list.** Re-run the step-5b grep: if any named
   ID is already `in-progress`, stop and say so — it may be another session's lane. 🚫 Do
   not release, re-date or edit that claim to clear the way, however stale it looks.
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
   to a lane already claimed instead of starting a new one.

   **The directive IS the operator's OK for this push** — a claim exists to be seen, by a
   second session, the other operator, a second machine; a local-only claim protects
   only this machine. Other main-direct commits startup already made (the backfill, a
   staleness fix) ride along; the script's guard has checked every one of them.

   ⚠️ The marker says `WORKTREE PENDING`, not `ACTIVE LANE`, and names no worktree — it
   does not exist yet; `worktree-increment` step 2 flips it the moment `git worktree add`
   returns. Never hand-write a claim marker while the script is reachable: a hand-written
   one drifts from the spelling the doctor reads (`incidents.md` → "The slice claimed by
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
