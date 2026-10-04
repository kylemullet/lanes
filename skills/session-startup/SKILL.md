---
name: session-startup
description: Use at the start of a working session on any machine of a repo that runs the lanes protocol. Triggers include "GA", "good morning", "what's in the queue", "startup", "let's get started", "catch me up", or any session-opening signal. Pulls the main branch, identifies the operator and machine from the lanes config, runs the project's preflight, closes verified issues on the certifying machine, builds the exclusion set of in-flight claims, and renders the five-block queue report ending in a recommended slice — then STOPS and waits for the operator to name the work.
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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lanes_doctor.py"
```

The `config` line names the mode and THIS machine's operator row: id, `short`, whether it
`certifies` (may land on the main branch and run the backfill) and whether it may edit
code. Hold those four facts for the whole session. In solo mode the machine certifies
and edits everything, and every two-operator step below is a no-op. In a multi-operator
repo an unknown `(user.name, platform)` pair resolves to **no permissions**: ask, do not
guess.

Keys this skill binds to: `git.main_branch`, `backlog.dir`, `backlog.view_port`,
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

### 2d. Close verified issues — the certifying machine only

A worktree lane ends with its issue at `status: verified`, Resolution filled, `commit:`
null — the lane cannot know its resolving commit's hash (the close rides in that commit,
and the pre-push rebase rewrites it). Startup, which has just pulled, is where the hash
becomes knowable:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py" --backfill --dry-run    # what would close, and what can't
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py" --backfill --commit     # fill commit:, flip to closed, ONE commit by path
```

For every `verified` issue it finds the resolving commit on HEAD by the exact subject the
Resolution cites in backticks, fills `commit:`, sets `status: closed` (+ `closed:` today
if the lane left it null), and — with `--commit` — stages ONLY those issue files and
commits `docs(backlog): close <IDs> — backfill resolving commit hash`. **No push.** The
commit rides to origin with the next push; mention it in the Brief.

Rules:

- **Gate: this machine's row `certifies`.** The script enforces it itself and refuses
  elsewhere. A non-certifying machine's brief lists verified issues as *awaiting the
  certifying operator's close* and leaves the files alone. One writer, no two-clone race
  on the same issue files.
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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py"              # rebuild the LOCAL, gitignored views
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py" --report     # this machine's operator; --who <short>|both
```

**Also start the served view, detached, if it is not already up** (`run_in_background`),
from the MAIN CHECKOUT:

```bash
curl -s -m 2 http://127.0.0.1:<backlog.view_port>/ >/dev/null || python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py" --serve
```

It re-parses the backlog on every request, so **refreshing the bookmark IS the
regeneration** and no later step can leave the operator looking at a stale queue. The
written `INDEX.md` / `index.html` are the offline fallback; both are generated and must
stay gitignored (every concurrent lane rewrites them).

**The view's link is block II of the report, on its own line.** It is the operator's
whole queue — sortable, filterable, linking into each issue file — and it carries the
weight of "let me see everything and overrule the slice". Do NOT pass `--open` unless
asked; a browser window stealing focus every session is noise.

The report is the mechanical half. Yours: staleness judgment (step 6), the report blocks
(step 7), the slice (step 8). Titles compress — **read the issue file body before acting
on or recommending an item.**

Also sanity-check the tooling: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py"
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
| `ACTIVE LANE`, worktree named | worktree present, or branch exists / has commits | live — *building* / *branch pushed, awaiting the verdict* / *verified, awaiting the landing OK* |
| `WORKTREE PENDING` | none needed | live — *claimed, setting up*; route around it exactly as for an ACTIVE lane |
| `RESERVED, NOT STARTED` | none needed | queued behind the named lane |
| `ACTIVE LANE` | claim ≥15 min old AND no worktree AND no branch AND no commits | stale-claim candidate — a **question** in the Brief, never a takeover |

All four qualifiers on the last row are load-bearing. Note that "no session" is **not
checkable by any command** and never contributed evidence; the branch check is the only
signal visible across machines (`git worktree list` is local-only).

Then build the **exclusion set**: every `in-progress` ID, plus every not-closed issue that
**conflicts** with one — it touches a file in an ACTIVE marker's expected-files list, it
extends or depends on the same module that lane is changing, or the in-flight issue's own
file sequences it (*"queued behind"*). A bare `links:` entry is not a conflict by itself.

Blocks IV and V are drawn from what is left, and nothing else. Block III may name an
in-flight lane **only** when it needs a decision from the operator right now (a verified
branch awaiting the landing OK, a stale claim to release) — mark it `🔒 in flight` so it
cannot be mistaken for a pick. **The operator's own lanes are not an exception** — a claim
does not care whose it is. (`incidents.md` → "Our own claims in block V".)

### 6. Staleness pass

Backlog entries outlive their own resolution. Check the urgent candidates and anything
older than ~14 days against the newest session assets and `git log --oneline -20`: has a
later commit already closed it, or cleared the gate it names? Mark those `⚠️` in the
report. Never silently drop one — if an item no longer reproduces, *correcting the issue
file IS the deliverable*, and it is a Quick win (`status: closed`, `resolution: wont-do`
or `done`, Resolution filled).

### 7. Render the report — five blocks, everything in tables

Every block but the Brief is a table. Keep item text to a short noun phrase.

**I — Brief.** Bullets, one line each: sync result; what landed since last session;
anything needing a decision right now; the backfill result ("closed N verified: IDs —
commit pending push" / "N verified awaiting the certifying machine's close"); whatever
`preflight.md` asked to report; unlanded branches from step 2; **the in-flight lanes from
step 5b — one line each: ID, ACTIVE/PENDING/RESERVED, lane state, what it is waiting on**;
the backlog stat (`N open · X critical · oldest Nd`).

**II — Sortable backlog.** The view's link alone on its own line, immediately after the
Brief — `http://127.0.0.1:<view_port>/` when served, else the `file://` path the generator
printed. Nothing else in the block. It goes HIGH because it is the operator's escape
hatch from the ordering below.

**Every item in blocks III–V is cited by its real ID with its IDENTICAL title.** Sub-tasks
within one issue are one row (`CORE-2 · 2 sub-tasks`), never rows that look like separate
issues.

**III — Critical (3–5 rows).** Timely and urgent only: blocking someone, needing a
decision, or actively costing something. Not a priority dump.

```
| ID | Item | What it is | Why now | Blocked on |
```

**IV — Quick wins.** Self-contained, closable in one sitting, no upstream dependency. The
relief valve. Staleness corrections from step 6 go here.

```
| ID | Item | What it is | Est | Blocked on |
```

**V — Recommended slice.** One line of thesis, then the table, then one line naming the
first concrete action and one naming what is explicitly parked. One issue = ONE row.

```
| ID | Item | Why it's in the slice | Blocked on |
```

**Block V never contains an `in-progress` issue or anything in the exclusion set.** It is
the *next* slice, and its thesis line says so when a lane is in flight (*"after CORE-31
lands: …"*).

**There is no full-backlog table.** Block II's view beats any static table, and the
`--report` output already printed the rows to the terminal. (`incidents.md` → "The full
table that oscillated".)

### 8. Choose the slice (block V) — by operator

**A code-editing operator with long sessions — the enemy is context-switching.** ONE
slice: a single project (or a machinery-sharing cluster within one) so one context load
closes several issues. In order: only from step 5b's eligible set; a hard blocker on the
other operator first, if one exists; else the highest-priority cluster where ≥2 open
issues touch the same files; prefer the slice that ends in something for the other
operator to author, verify or ratify; name what is parked.

**A non-code operator with short sessions — the enemy is picking wrong.** Block V becomes
1–3 independent picks, each genuinely theirs (authoring, domain judgment, product
decisions), batched by context, with an honest cost in the `Est` column using measured
numbers where they exist and estimates labelled as estimates.

**Solo mode:** the first shape. There is no other operator to give runway to.

**Then STOP and wait.** Block V is a recommendation, not an assignment — startup does NOT
begin work. End the message by asking what the operator wants to work on. Work begins only
when they name it ("do X", "run the slice", "go"). Sole exception: a staleness correction
from step 6 is part of the report itself.

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
the same rule on the edit tools; it never sees a write made through Bash, so the two
commands stay.

**The reply to "go" states the order before starting:**

> Slice is CORE-64, UI-40, INFRA-31. Working them one at a time, each in its own worktree
> off a fresh main, baseline read before each. Starting CORE-64 in `../<repo>-core-64`; I
> will report before opening the next.

If the operator wants them parallel they will say so, and that means **one Claude Code
session per worktree** — never one session juggling several. (`incidents.md` → "The day
with no product work".)

### 8b. On the directive — claim, commit, PUSH, then hand off

"go", "run the slice", "do CORE-64", "work X then Y" — any directive naming one issue, a
group, or the recommended slice. This is the ONE write startup makes in the main checkout
after the brief, and it happens *before* the first worktree exists:

1. **Resolve the directive to an ordered ID list.** Re-run the step-5b grep: if any named
   ID is already `in-progress`, stop and say so — it may be another session's lane. 🚫 Do
   not release, re-date or edit that claim to clear the way, however stale it looks.
2. **Claim every ID now, up front**: the first gets the `WORKTREE PENDING` marker with its
   expected-files list, the rest get `RESERVED, NOT STARTED — queued behind <ID>`.
   Frontmatter `status: in-progress` **and** the body marker, both.

   ⚠️ **`WORKTREE PENDING`, not `ACTIVE LANE`, and no worktree name** — the worktree does
   not exist yet; `worktree-increment` step 2 flips it the moment `git worktree add`
   returns. Every marker's timestamp is LOCAL with minutes: `date "+%Y-%m-%d %H:%M"`.

   Then both of:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py" --check    # the integrity gate
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py"            # rewrite the local views
   ```

3. **One commit, staged by explicit path** — the issue files only; the generated views are
   gitignored and never part of it.
4. **Main-direct guard, then push to `origin/<main_branch>`:**

   ```bash
   git log origin/<main_branch>..<main_branch> --name-only --format= | sort -u
   ```

   Every path must match `git.main_direct_paths`. Anything else on local main means code
   was committed on the main branch — stop and surface it, do not push. Otherwise push.
   **The directive IS the operator's OK for this push** — a claim exists to be seen, by a
   second session, the other operator, a second machine; a local-only claim protects
   only this machine. Other main-direct commits startup already made (the backfill, a
   staleness fix) ride along; the guard has just checked every one of them.
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
  except the claim push (8b), where the directive is the OK and the main-direct guard is
  the safety.

## What this skill is NOT

Not a state-repair tool — unexpected merge conflicts, unrecognized files, or a
force-push situation: stop and investigate with the operator.
