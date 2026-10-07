---
name: session-closeout
description: Use when the operator is wrapping up a working session on a repo that runs the lanes protocol and wants the loose ends tied off. Triggers include "let's wrap", "session close", "wrap up", "let's call it", "before I go", "end of session", "close out", or any explicit end-of-session signal. Sweeps every worktree, commits shared text, reconciles the backlog and releases this session's unreached claims, runs the project's pre-land checks and the test gate, pushes branches freely, and confirms before anything lands on the main branch.
---

# Session closeout

## Why this skill exists

Cross-machine sync depends on a clean session boundary: whoever is working commits,
rebases onto the main branch, and lands; the next `session-startup` anywhere pulls it. If
the backlog is stale, if uncommitted work is left dangling, if shared text never lands in
git, or if code sits on a branch nobody merged, the next session reads the wrong state.
Every machine runs this same skill; some gates are operator-specific and some are
**machine**-specific, and both are marked. The failures behind the rules:
[`references/incidents.md`](references/incidents.md).

**Config keys this skill binds to:** `git.main_branch`, `git.main_direct_paths`,
`git.land_requires_ok`, `backlog.dir`, `tests.command`, `tests.required_before_land`,
`operators[]`, `lanes.code`. Read them via `sh
"${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_doctor.py` (the `config` line) at step 0.

## Procedure

### 0. Identify the operator AND the machine

From the doctor's `config` line: this machine's operator row — `certifies`? may edit
code? Solo mode: both yes. Which gates fire:

| | certifying machine | non-certifying machine |
| :-- | :-- | :-- |
| Code may change | ✅ (if the row may edit code) | ❌ |
| Full test gate (step 5) | ✅ required when code changed | n/a — code never changes here |
| May land on the main branch | ✅ code + docs | docs (main-direct paths) only |

### 1. Surface session state

Run in parallel:

- `git status` — uncommitted work, untracked files, branch position.
- `git log origin/<main_branch>..HEAD --oneline` — unlanded commits, and which branch
  they are on. **If code changed, they must be on a named branch, not the main branch** —
  a code commit sitting on the local main branch is a policy miss; move it (`git branch
  <topic>-work && git reset --hard origin/<main_branch>`) before going on.
- Recall what was done this session from conversation context — don't re-read code.
- **If any code changed this session on a certifying machine, kick off the full
  `tests.command` NOW in the background** (step 5) so it finishes during the doc
  back-and-forth.
- **A non-code operator whose `git status` shows changes under `lanes.code` — stop.**
  Don't commit or push those; surface them, revert or stash, and queue the underlying
  need as an issue for the code owner.
- Whatever `.claude/lanes/preflight.md` launched at startup and asked to report on
  (a long-running measurement, a local server): report its state in one line.

### 1b. 🚨 Sweep EVERY worktree, not just this one

`git status` answers for the directory you are standing in. A session that used
worktrees has other directories, and work stranded in one of them is invisible to every
check above.

```bash
git worktree list
git branch -r --no-merged origin/<main_branch>
git stash list
pgrep -fl "<tests.command>"
```

Then, for EACH worktree path the first command printed, the two checks that `git status` in
this directory cannot answer for it:

```bash
git -C <worktree> status --porcelain=v1 -b
git -C <worktree> log --oneline @{u}..HEAD     # fails with "no upstream" = never pushed
```

Act on what it finds, in this order:

0. **An orphaned suite still running** — belonging to a lane that is finished, or to a
   session that was stopped. **Leave it alone; let it finish.** Do NOT kill another
   session's background process: a task ending — including by `kill` — counts as that task
   *completing*, which re-invokes the session that owns it (`incidents.md` → "A stopped
   session is not a dead session"). Note it in the handoff; the machine is busy until it
   ends.
1. **Uncommitted work in any worktree** — commit it on that worktree's branch and push the
   branch. A branch push is free, carries no test gate and cannot move the main branch.
   There is no reason to end a session with finished work uncommitted, or committed work
   unpushed.
2. **A branch with no upstream** — push it. It exists only on this disk otherwise.
3. **A worktree whose lane is finished and landed** — remove it, so the next session's
   sweep stays meaningful. Its branch goes too, but only once
   `git merge-base --is-ancestor <branch> origin/<main_branch>` passes: a branch that is
   only pushed is the lane's one copy off this machine. Never in the same command line as
   a landing.
4. **A worktree whose lane is unfinished** — say so explicitly in the summary, naming the
   issue and what it is waiting on. A worktree the operator has forgotten about is how a
   lane dies. (`incidents.md` → "~24 files, one rm -rf from gone".)

### 1a. 🚨 Shared text content MUST commit before push

**Critical rule, no exceptions, every machine:** any untracked project text MUST be
committed before the closeout push, even if this session never processed it — a new
session asset under `docs/session-assets/`, and any text the project's `preflight.md`
names as shared (data-mirror notes, fixture ground truth). Text that is not on the main
branch is invisible to every surface except the machine it was written on.

**How to detect — use this exact command:**

```bash
git status --porcelain --untracked-files=all | grep '^??'
```

**Do NOT use a git pathspec glob** (`git status -- 'dir/**'`) — that form silently
matches nothing and reported a false "(none)" once over a real asset. Commit the text;
leave binaries and sync-tool metadata (gitignored anyway). Bundle the catch-up as its own
commit so cross-machine sync content stays legible in `git log`.

### 2. Reconcile the backlog

The backlog is the queue's source of truth; issue frontmatter is state, issue bodies are
current understanding. At every closeout, either operator:

- **Close what this session finished:** in each issue file — `status: closed` (or
  `verified`, if a lane landed and the certifying machine's backfill will close it),
  `closed: YYYY-MM-DD`, `resolution:` set, the **Resolution** section filled naming the
  resolving commit by its **subject**. `commit:` (short hash) is optional — fill it only
  for a commit already on `origin/<main_branch>`, otherwise leave `null`: a hash cited
  before push is rewritten by the step-7 rebase and is a dead link elsewhere. An issue
  closed without a change is `resolution: wont-do`, `commit: null`. Each operator's
  closures of their own issues are authoritative.
- **Sweep the verified issues — certifying machines, done and reported, never offered:**

  ```bash
  sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --backfill --push
  ```

  A lane landed through `lanes_land.py` closed its own issue; this catches the rest — a
  lane landed by hand, or by another session — so `verified` rows do not sit until the
  next startup. Use `--commit` instead where the project does not let a backlog-only
  push reach the main branch without an OK. A SKIPPED issue is a finding: fix its
  Resolution (session-startup step 2d) rather than leaving it for the next session.
- **Queue what this session surfaced:** one issue per new item —

  ```bash
  sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_new.py <PROJECT> "<title>" --type=… --priority=… --assignee=… --reported-by=…
  ```

  then write its Context. `--reported-by` is REQUIRED and has no default: the operator's
  short when they raised it, `claude` when this session did. **Producer decomposes** —
  whatever the OTHER operator must act on becomes an issue with their `assignee`, not
  prose in a session asset; their next startup reads the queue and there is no
  consumer-side digest step.
- **Update what moved:** an issue whose understanding changed gets its **Current status**
  (and Context, if the framing changed) **overwritten** — not appended to. History lives
  in git blame + session assets. If the blocker changed, update `blocked_on`; if the
  urgency changed, `priority`.
- **Release every RESERVED claim the session never reached.** A slice claims all its
  issues up front, so a session that runs out of time leaves `status: in-progress` on
  issues with no worktree and nobody behind them, and those poison every future conflict
  scan. For each slice issue still marked `RESERVED, NOT STARTED`: set `status` back to
  what it should now carry (`open`, or `blocked` / `paused` if that was its prior state),
  delete its `lane:` line, and overwrite the ⏳ marker to say it was claimed and not reached. An issue that WAS
  worked and is parked mid-flight keeps its claim — that is a live lane.

  🚫 **Release only THIS session's own claims.** Closeout is where a claim is released
  precisely because the session releasing it is the one that made it. Another session's
  claim — including one that looks stale, misdated or abandoned — is **surfaced in the
  handoff and left untouched**, even here, even when it is obviously wrong. Only the
  operator saying so, by ID, releases someone else's claim.

  ```bash
  grep -rln "RESERVED, NOT STARTED" <backlog.dir>
  ```
- **Run the backlog check:**

  ```bash
  sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --check
  ```

  Structural problems, orphaned claims, orphaned `commit:` hashes, verified issues whose
  cited subject is missing or whose code change has no `Docs:` line. The generated views
  are local — regenerate for your own reading, never commit them.
- **Extension point: `.claude/lanes/pre-land.md`.** If it exists, read it now and run what
  it says — a project's own integrity checks (a data manifest, an output gate, a generated
  report to refresh). Drift it reports is a finding for the summary, never something to
  regenerate over.

### 2b. The other operator's issues — keep them honest (multi-operator only)

Everything waiting on the other operator is an issue with their `assignee` (or `shared`).
Add new asks as issues with an honest time budget in the body — recorded actuals over
estimates. `opened` dates make staleness visible in `--report`; never backdate or wipe
them. Solo mode: nothing to do.

### 2c. Standing-context docs — structural changes only

The project's standing-context document(s): update in place if a *standing fact* changed
this session — a scope line, a locked decision, a collaboration mechanic. Overwrite the
section; don't append. Per-issue numbers and fixture counts live in issues and feature
docs; leave the standing docs alone for those.

### 2d. The authoring lane's doc loop

A code lane closes its doc loop inside `worktree-increment` (step 8a); an authoring lane
(fixtures, ratifications, verification verdicts — anything that never enters a worktree)
has no increment skill, so its loop closes here. **Run it for every piece of authoring
this session produced**, deriving the candidate docs mechanically — grep the project's
docs for the thing authored, never ask "did anything change?" — then the same three-way
triage as the increment skill: a paragraph gets edited now and rides in this closeout's
docs commit; a new surface or a rewrite gets a DOC issue; and **the outcome goes into the
closed issue's Resolution as a `Docs:` line**, "nothing" included. Authoring is docs-lane
by path, so `--check` does NOT enforce the line here the way it does for a code lane — the
line is what tells the other operator's next startup that the standing docs were
considered.

### 3. Session asset check

An asset belongs in `docs/session-assets/YYYY-MM-DD - <author> - <topic>.md` when the
session produced: substantive code change, a finding worth preserving without code, a
convention or principle change, or substantive verification / authoring work. NOT
warranted for doc-only updates the backlog already captures. Borderline → ask. Markdown
only. Link the asset from the issues it explains.

**The doc-loop backstop is mechanical — do not re-verify it by hand.** `backlog_index.py
--check` (step 2, and again in step 7 after the rebase) fails any `verified` issue whose
change reached outside the docs lane without a `Docs:` line in its Resolution. If it
reports one here, the fix is the increment's, not the closeout's: add the line to that
Resolution in a docs commit that names the increment, and do **not** do the doc review
itself at the session boundary — that is how the obligation migrates back to where it
never got done.

### 4. Memory check

Work-state changes → the backlog. *Principle* changes (new convention, collaboration
mechanic, stable fact about an operator) → the session's memory, proposed before writing.
Most sessions: no memory change. A principle change worth remembering should ALSO land in
a tracked doc so the other machines' sessions learn it too.

### 5. 🟢 Test gate — code changed on a certifying machine

**If any code changed, run the ENTIRE `tests.command` before landing** — no path filter.
Targeted runs during the session don't substitute: cross-module regressions and
pre-existing reds on the main branch are the two classes only a full run catches, and
both have happened. Run in background. **Any red ⇒ no landing** — diagnose, fix or get
the operator's explicit deferral (logged in the relevant issue), and report exact counts.
`tests.required_before_land = false` turns this step off for a project that has no suite;
nothing else does.

Non-code operators: the gate doesn't apply *because code never changes on their machine*
(step 1 enforces that). Doc-only changes land without it — on every machine.

### 6. Commit discipline

- Logical commits, one topic each; stage files explicitly by name — never `git add -A` /
  `git add .`. Backlog edits ride with the work they describe; generated views are never
  staged.
- Message: short subject + 2–4 sentence why-body + the standard `Co-Authored-By:` trailer
  for the model running.
- Moved or renamed files: confirm with the operator first.

### 7. Rebase, then confirm before landing on the main branch

**The OK gate is on LANDING, not on `git push`.** Two different actions, two rules:

- **Pushing a topic branch is free and autonomous** — `git push -u origin <branch>`. It
  cannot move the main branch, cannot affect the other operator, and is how work survives
  a machine. Do it without asking.
- **Anything that moves `origin/<main_branch>` needs the operator's explicit OK** while
  `git.land_requires_ok` is true — a push from a checked-out main branch, or `git push
  <branch>:<main_branch>`.

Docs, backlog issues and session assets (`git.main_direct_paths`) land on the main
branch directly, from every machine. Code lands from its branch, and only from a
certifying machine (step 5).

**Always `git pull --rebase` immediately before landing** — another machine may have
landed mid-session. Per-issue files rarely conflict; the generated views cannot (they are
gitignored). For a shared standing-context doc, each author is authoritative for their
own edits; merge both.

**Then, AFTER the rebase, re-run the backlog check — required, not a nicety:**

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --check
```

Ordering is the whole point: a rebase rewrites every commit hash cited since the branch
point, so a `commit:` filled before the rebase is now an orphan. If it fails: repoint the
citation (subject in the Resolution, `commit: null` or the rewritten hash), amend,
re-check.

**Read every status check off its own line — never through a pipeline.** `git pull
--rebase 2>&1 | tail -5` reports *`tail`'s* status, so a rebase that stopped on a conflict
reads as success and whatever is chained next runs on top of it. Redirect to a log, echo
the exit status on its own line, then read it. **A status check that cannot fail is worse than no check** — it reads
as verification in the transcript while establishing nothing.

Then **confirm explicitly before the landing push, enumerated by lane**: *"Land CORE-64,
UI-40 and INFRA-31 (11 commits) on origin/<main_branch>?"* — not a bare commit count. A
branch push that happened earlier needs no such confirmation and should not be
re-litigated here.

- **A worktree still in place means a lane that did not finish.** Say which and why
  (awaiting a verdict, parked red) — do not remove it, and do not land it without the OK
  the increment skill would have asked for.
- **A held lane must still be pushed as a branch.** Check `@{u}..HEAD` on every worktree
  (step 1b already did) and push anything unpushed BEFORE asking about the landing.

### 8. Post-push note

No extra sync step. Landing on the main branch is all that is needed — the other
machines pick it up on their next `session-startup` pull.

**A branch that did not land is not synced.** It is visible to the other machines but
reaches nobody's working state. Name it in the summary with what it is waiting on, and
make sure the issue it belongs to says the same (`status`, **Current status**) — an
unlanded branch with a silent issue is "shared state that never reached the main branch"
wearing a better outfit.

### 8a. Extension point: `.claude/lanes/pre-land.md`, the shutdown half

If the project's `pre-land.md` names things to shut down (a local server started at
startup, a watcher), do them AFTER the push/summary conversation, not earlier — the
operator may be using them right up to the end. Scope any port sweep to what this
checkout owns; never tidy a band another lane may be verifying in.

### 9. Final state summary

One paragraph: what shipped/verified, which issues closed/opened for each operator, test
counts (code sessions). The next session on any machine picks up from here via
`session-startup`.

## Output shape

1. Surface state (incl. which branch the commits are on) + (code changed) kick off the
   suite in background.
2. Wait for operator confirmation on non-trivial edits.
3. Execute the agreed pieces.
4. (Code changed) gate on the green suite — a certifying machine only.
5. Push the topic branch (no OK needed); rebase; confirm the LANDING by lane.
6. Final summary, naming any branch left unlanded and what it waits on.

## What this skill is NOT

- Not code-review; not a deploy step (landing on the main branch IS the publish event).
- Not state-repair: merge conflicts you can't attribute, unrecognized files, or an
  unexpectedly diverged branch → stop and investigate before proceeding.

## Safety reminders

- Never `git add -A` / `git add .` — explicit paths only.
- Never force-push the main branch; never amend a pushed commit.
- Never land code on the main branch from a machine that cannot certify it, and never
  commit code on the local main branch in the first place.
- Never land red tests. A red verdict that arrives AFTER landing from another platform is
  a bug to fix forward, not a reason to revert.
- Never kill another session's running process.
- Never `git clean -fdx` at repo root — a project may mount live-synced content there.
- Never hand-edit or commit the generated backlog views.
