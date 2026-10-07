---
name: worktree-increment
description: "Use when the operator assigns ONE backlog issue (an ID like CORE-2 or INFRA-7) to be worked in an isolated git worktree — the standard flow for running one or more sessions, each targeting its own increment. ALSO the flow for a multi-issue slice — invoked once per issue, sequentially, never widened to cover several at once. Triggers include \"work CORE-<N> in a worktree\", \"do this issue in a worktree\", \"run the slice\", \"go\" after a startup brief, or any assignment naming backlog issues. Covers the full lifecycle: claim → worktree → build → self-verify → hold → operator verify → fix/log → commit → push → land (with OK) → clean up."
---

# Worktree increment

## Why this skill exists

Several sessions may work one repository at once, each on one queue item in its own
worktree. The worktree isolates working files; everything else that made
one-session-at-a-time safe now has to be explicit: who claimed what, which checkout a
local server serves, whose push lands first, and how the second lane rebases. This is the
ratified sequence. Deviations that matter get surfaced to the operator, not improvised.
The failures behind each rule: [`references/incidents.md`](references/incidents.md).

**Config keys this skill binds to:** `git.main_branch`, `git.main_direct_paths`,
`git.land_requires_ok`, `backlog.dir`, `backlog.docs_lane_prefixes`, `tests.command`,
`tests.required_before_land`, `tests.rebase_rerun_command`, `worktrees.port_command`,
`operators[]`. Read them once via `sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_doctor.py`
(the `config` line) or the file itself.

Ground rules that apply the whole way through:

- **The OK gate is on LANDING on the main branch, not on `git push`.** Pushing this lane's
  topic branch is free and autonomous — it cannot move `origin/<main_branch>`, and it is
  how the increment survives the machine and travels to a certifying one. `git push
  <branch>:<main_branch>` — the landing — always needs the operator's explicit OK while
  `git.land_requires_ok` is true. The step-1 claim push is a main-branch push
  pre-authorized by the directive that started the work, under the main-direct guard.
- **Only a machine whose operator row `certifies` lands code** (solo mode: this one). Its
  green run of `tests.command` is the whole pre-landing gate. A lane never ends at
  "awaiting another machine".
- Stage by explicit path, never `git add -A` / `.`.
- Tests gate commits: a full green `tests.command` before any commit of code.
- A local server, if the project has one, runs on **this lane's own port**
  (`worktrees.port_command` from the worktree root); never a shared default port.

## Scope: ONE issue per invocation — this is a hard boundary

**If the operator names more than one issue, this skill runs once per issue,
sequentially.** It does not widen to cover a slice.

**Claims are the exception: make them for the WHOLE slice, up front.** Claiming and
working have different jobs and do not share a cadence. A claim exists so a concurrent
session does not open the same issue; it says nothing about which lane is active. In the
operator's words: *"even if we end up not working those for one reason or another, the
claim should still be valid, because I'm not going to open that same issue in another
worktree."*

So: **one claim commit covering every issue in the slice, committed AND pushed to
`origin/<main_branch>` before the first worktree is created.** Normally `session-startup`
step 8b has done this on the directive, and step 1 here only verifies it. Use the body
marker to distinguish states, since `status: in-progress` is doing collision duty for all
of them:

The three markers, each on one line (copy them exactly — the doctor and the
conflict scan match these strings):

```
⏳ IN-PROGRESS (YYYY-MM-DD HH:MM, <operator>'s session) — **WORKTREE PENDING.** Claim pushed; worktree not yet created. Expected files: …
⏳ IN-PROGRESS (YYYY-MM-DD HH:MM, <operator>'s session, worktree <name>, branch <branch>) — **ACTIVE LANE.** Expected files: …
⏳ IN-PROGRESS (YYYY-MM-DD HH:MM, <operator>'s session) — **RESERVED, NOT STARTED.** Claimed as part of the <date> slice, queued behind <ID>. No worktree yet and no files touched.
```

**Timestamps are LOCAL and carry minutes** (`date "+%Y-%m-%d %H:%M"`, never UTC). A date
alone cannot answer "is this claim two minutes old or two days old", which is the only
question a stale-claim check needs.

**`WORKTREE PENDING` exists because the claim is pushed BEFORE the worktree is created,
and that gap is real** (`incidents.md` → "113 seconds"). A second session seeing PENDING
routes around the issue exactly as it would for an active lane; nothing has to be
inferred.

A reserved issue the session never reaches is **released at closeout**, not left claimed:
set it back to the status it should carry and clear the marker. An `in-progress` issue
with no live worktree and no session behind it poisons every future conflict scan.

Concretely, handed "CORE-64, UI-40, INFRA-31": claim all three now (CORE-64 PENDING, the
other two RESERVED); work CORE-64 start to finish — worktree, build, verify, land or park,
**remove the worktree**; pull main again and take the baseline for the new tip; only then
begin UI-40, in its own worktree, flipping its marker from RESERVED to PENDING then
ACTIVE as it starts.

**Never open the second lane while the first is unresolved**, and "unresolved" includes
*waiting on the operator's verdict*. Genuine parallelism means **one Claude Code session
per worktree**.

### 0. Assert your position BEFORE the first edit

Two commands, every time, before any file write that is not the step-1 claim:

```bash
git rev-parse --show-toplevel     # must NOT be the main clone
git rev-parse --abbrev-ref HEAD   # must NOT be the main branch
```

If the first prints the main clone or the second prints the main branch, **stop and make
the worktree.** Every incident this flow exists to prevent begins with an edit made in
the main checkout because it was one command closer. **The one exception is the step-1
claim**, which is main-direct by design.

**Enforced mechanically by the plugin's position-guard hook** on the edit tools
(`Write` / `Edit` / `MultiEdit` / `NotebookEdit`). It refuses a write that would land in
the main clone OR on the main branch, and allows exactly two shapes: a lane write (not the
main clone AND not the main branch) and the claim's shape (main clone AND main branch AND
a `git.main_direct_paths` path). Two limits, said plainly: it never sees a write made
through Bash (`sed -i`, a heredoc), so the two commands above are still the rule; and a
session loads hooks from the directory it STARTED in.

## Procedure

### 1. Sync main + claim the item

Work happens in the MAIN checkout before the worktree exists:

1. `git pull --ff-only` on the main branch. If it won't fast-forward, stop and surface —
   someone left local commits on the main branch.

   **Then obtain the BASELINE for that tip:** the collected test counts (passed / failed
   / skipped) at this exact commit, which step 4 compares against so the lane can tell its
   own breakage from a pre-existing red and from a short environment. If
   `.claude/lanes/lane-setup.md` or `preflight.md` names a measurement that already
   exists for this tip (a ledger row, a CI run), read it; otherwise run `tests.command`
   once here and record the counts in the claim marker. A **known red** at the tip is not
   a stop: if it is already attributed to an issue, write the IDs into the marker so step
   4 can subtract them; an *unattributed* red IS the finding — surface it. If you do run a
   suite by hand, check first (`pgrep -fl "<tests.command>"`) that one is not already
   running against the same tip: a duplicate run buys nothing and slows both.
2. **Conflict scan — frontmatter first, it is the authoritative signal:**

   ```bash
   grep -rln "^status: in-progress" <backlog.dir>
   ```

   That list IS the set of live claims. For each hit, read that file's **Current status**
   section for the ⏳ marker's expected-files list and compare against what this item will
   touch. If another claim names files this item will touch, tell the operator before
   proceeding — the answer may be "sequence it" or "accept rebase duty" (whoever lands
   second rebases; behavior-neutral refactors land first when possible).

   🚫 **You never write to another issue's claim. Not the marker, not the frontmatter, not
   the timestamp, not a typo in it.** Releasing or amending a claim belongs to exactly two
   actors: the session that OWNS it (at closeout), or an explicit operator instruction
   naming that issue. A claim that looks stale, wrong, abandoned, misdated or absurd is
   still not yours — **say so and stop.** An intention can be complied with while being
   violated; a prohibition cannot (`incidents.md` → "The takeover with an opt-out").

   **Do NOT drive the scan off a bare grep for the marker text.** A closed issue whose
   body QUOTES a historical marker matches forever; frontmatter cannot be poisoned this
   way. As belt-and-braces for the inverse failure (a body marker left behind on an issue
   whose frontmatter was cleared), run `grep -rln "IN-PROGRESS" <backlog.dir>` too and
   treat any hit NOT in the frontmatter list as stale-until-proven-live — fix it rather
   than reporting a conflict. `backlog.claim_marker_exempt` lists the issues that
   legitimately quote one.
3. **Claim** — unless it is already made (`session-startup` 8b: frontmatter `in-progress`,
   the ⏳ marker names this session, the claim commit is on `origin/<main_branch>`). If so,
   confirm the expected-files list and skip to step 2. Otherwise, in the item's issue file,
   do BOTH halves — they are read by different things and one without the other is the
   bug:

   a. **Frontmatter:** `status: in-progress`. This is what the views and `--report` render
      — what the other operator sees. Note the prior status; if the item was `paused` or
      `blocked`, restore that rather than `open` if the increment is abandoned.
   b. **Body:** overwrite **Current status** with the `WORKTREE PENDING` marker plus the
      expected-files list — the load-bearing part, what the other session reads once its
      frontmatter scan points it at your file. ⚠️ Not `ACTIVE LANE`, no worktree name yet.

   Then `sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --check` and, for the
   browsable view, `sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --root
   "$(git rev-parse --git-common-dir)/.."` — **the main clone's root is the point**: run
   from a worktree, the script indexes the WORKTREE and the operator's bookmark points at
   the main clone's files. (If the served view is up, it is already current.)
4. **Commit the claim (explicit path: the issue files) AND push it to
   `origin/<main_branch>`.** The main-direct guard first, every time:

   ```bash
   git log origin/<main_branch>..<main_branch> --name-only --format= | sort -u
   ```

   Every path must match `git.main_direct_paths`. Anything else on the local main branch
   means code was committed there, which the branch policy forbids: stop and surface it.
   Otherwise push. **The directive that started this work is the OK for this push.**

   ⚠️ **Run the conflict scan (1.2) in the MAIN CHECKOUT, never in a worktree.** A worktree
   created off the main branch before the claim push does not contain the claim.

### 2. Create the worktree

`git worktree add ../<repo>-<topic> -b <topic>-work` (or the harness worktree tool).
Then:

- Confirm the worktree HEAD == the main tip you just synced.
- **Flip the marker to `ACTIVE LANE` and push it — immediately, before any other setup.**
  In the MAIN CHECKOUT, rewrite the marker from `WORKTREE PENDING` to `ACTIVE LANE` with
  the worktree and branch names, commit by explicit path, run the step-1.4 guard, push.
- **Then push the topic branch straight away, while it is still empty:**

  ```bash
  git -C <worktree> push -u origin <branch>
  ```

  `git worktree list` is LOCAL — it is no evidence to the other operator or a second
  machine, which can only see the branch. Between these two pushes the window closes in
  both directions: the marker is accurate locally, and the branch exists remotely.
- **Extension point: `.claude/lanes/lane-setup.md`.** If it exists, read it now and do what
  it says — fixtures or data to copy in, an environment or `node_modules` to link, a port
  to resolve. Everything true of one project only lives there, not here.

### 3. Work the item

Normal build discipline. Scope stays on the assigned item: in-scope discoveries get fixed;
out-of-scope discoveries get LOGGED (step 8), not chased.

### 4. Self-verify

**Rebase FIRST, then verify — not the other way round.** `git fetch origin`; if
`origin/<main_branch>` moved, rebase onto it BEFORE the suite runs. A green on a tree that
is already behind buys nothing — step 6.1 has to re-establish it anyway. The old order
(verify → hold → rebase → re-verify) cost a lane up to three full suites.

- Full `tests.command` — green, zero failures. An environment failure means step 2's
  setup was skipped or stale; re-supply, don't rationalize. Keep the machine awake for
  an unattended run (`incidents.md` → "The suite that slept").
- **Compare COLLECTED against step 1's baseline, not just the exit status.** Green is not
  the property; *green over the same corpus* is. A worktree missing a data mirror still
  passes — it simply never collects the dependent tests, and the only trace is extra skips.

  ```
  baseline (step 1):   passed + skipped = N
  worktree (here):     passed + skipped = N + <tests this lane added>
  ```

  Reconcile to test IDs (`--collect-only`, then `comm` the two trees) rather than to the
  totals; totals can agree by coincidence. Anything less means the environment is short,
  not that the code is fine. A `known red` from the baseline is subtracted the same way —
  one attributed failure, not this lane's, unless this lane is the one fixing it.
- For visual or UX-touching work, auto-tests-green ≠ shipped — the operator's eyes in step
  6 are the other half of the gate.

### 5. Hold

Leave the work UNCOMMITTED in the worktree until the operator verifies. (For rebase
mechanics during the hold: a temporary WIP commit → rebase → `git reset --mixed HEAD~1`
restores the uncommitted state exactly.) Announce readiness and what verification will
cover; then wait — do not commit, do not push.

**Generated files stay out of the WIP commit.** Stage by explicit path.

**Check the rebase's exit status on its own line.** `git rebase origin/main | tail -5 &&
<next>` reports the *pipeline's* last command, so a rebase that stopped on a conflict
looks like success and the `&&` chain runs on — once all the way to `git reset --mixed
HEAD~1` *inside* a conflicted rebase. Redirect to a log, echo `$?`, then read it.

### 6. Stage the operator verification

When the operator says they are ready:

1. `git fetch origin`. If `origin/<main_branch>` moved: WIP-commit → `git rebase` (exit
   status on its own line) → reset → re-supply any lane setup other lanes may have
   changed → **re-run what the incoming commits can actually reach.** With
   `tests.rebase_rerun_command` set, run exactly what it prints:

   ```bash
   <tests.command> $(<tests.rebase_rerun_command>)
   ```

   (Use the inline `$(...)` form — a variable holding the args is not word-split in
   every shell.) Without it, re-run the full `tests.command`. **Never hand-edit a verdict
   downward.** What backstops a miss: the next full run at the new tip, however the
   project produces one, surfaces a composite regression within one lane cycle — fixed
   forward, not blocked.
2. If the project has a build step for what the operator will look at, run it explicitly
   now (a launcher that only builds when output is MISSING serves a stale build after a
   rebase).
3. Resolve this lane's port with `worktrees.port_command`; kill whatever owns **that**
   port, never a shared default — a bare kill takes out another lane's server while its
   operator is looking at it. Start the server from the worktree root.
4. Confirm the served bundle == disk before handing over. Against a shared port that
   check compares THIS lane's disk to whatever server answers, and passes wrongly.
5. Hand the operator **concise test cases**: numbered, each with the file path, the exact
   action and the expected result. **Quote the FULL URL including the port**, and **say
   "reload the tab"** — an open tab keeps old JS in memory forever and reads exactly like
   the fix not working.

### 7. The operator verifies

Findings come back informally; sort each one in step 8.

### 8. Triage findings

- **In-scope defect** → fix it now, loop back to step 4.
- **Suspected regression** → before treating it as one, re-run headless against the
  documented baseline (the issue's or feature doc's recorded numbers). Byte-identical to
  the record = pre-existing, not this increment's problem — say so with the evidence.
- **Out-of-scope finding** → log it as a new backlog issue in the worktree:

  ```bash
  sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_new.py <PROJECT> "<title>" --type=… --assignee=… --reported-by=…
  ```

  `--reported-by` is REQUIRED — the operator's short when their verification surfaced
  it, `claude` when the lane did. It rides in this increment's commit.
- Repeat 4→8 until the operator is satisfied.

### 8a. Close the doc loop

Runs once, **after verification and before the step-9 backlog pass** — not earlier (the
increment can still change shape) and never deferred to `session-closeout` (that is a
session boundary; this is an increment obligation). The doc work rides in the SAME
resolving commit as the change that caused it.

**Skip only when every touched path matches `backlog.docs_lane_prefixes`.** Say "8a: n/a
(docs-lane only)" and move on. **Everything else runs it — tests, CI config, skills,
ignore files, dependency manifests included**: a project's standing docs describe CI, the
process and the test guards in prose, so each of those is a doc edit waiting to happen.
`backlog_index.py --check` enforces the OUTCOME (step 4 below), so a lane that skips this
step fails the push gate.

1. **Name the candidate docs mechanically** — never ask yourself "did anything change?";
   a yes/no prompt gets a no:
   ```bash
   git -C <worktree> diff --name-only origin/<main_branch> -- . <':!' for each docs-lane prefix>
   grep -rln "<touched path or dotted module name>" docs/ CLAUDE.md
   ```
   plus any table row naming the module in the project's standing docs. The infra class
   has fixed candidates the grep will not find, because the process is described in
   prose, not by path: a change under the skills or CI config → read the standing docs'
   process sections; a test file → grep its basename (docs cite guards by name).
2. **Read each candidate against the diff**: recorded numbers the increment moved;
   "not implemented / deferred" claims it just falsified; names it renamed; a "pending"
   frame it resolved.
3. **Triage, three ways:**

   | Case | Action |
   | :-- | :-- |
   | Small/local — the change contradicts a paragraph in an existing doc | **Edit the doc now**, staged into this increment's commit |
   | New surface — a module, seam, endpoint or view with no doc | **Queue a DOC issue**; do not write it inline |
   | Sufficiently complex — several docs, or the correct edit is a rewrite | **Queue a DOC issue** naming which docs and why one increment cannot carry it |

   Queuing is the default whenever the answer is not a paragraph.
4. **Record the outcome in the issue's Resolution — always.** A `Docs:` line (bare,
   `**Docs:**` or bulleted) naming what was edited or which DOC issue was queued —
   including `Docs: nothing — this increment changed no documented behavior`. Silence must
   be distinguishable from not having looked. `--check` fails any `verified` issue whose
   change reached outside the docs lane and whose Resolution has no `Docs:` line
   (`incidents.md` → "Six lanes without the line").

### 9. Commit + push the branch, then land (with OK)

1. Final backlog pass in the worktree: on the worked issue, move `status` off
   `in-progress` — to **`verified`** (NOT `closed`) with a filled Resolution and
   `resolution: done` (or `duplicate` / `superseded`, named in the prose), or, for a
   partial, back to the status it should now carry with Current status saying where it
   stopped. Either way the ⏳ marker goes too. **Both halves, again.**

   **`verified` means landed, awaiting close.** The lane never writes `closed` or a
   `commit:` hash: the hash is unknowable here. The certifying machine's next
   `session-startup` runs `--backfill`, which finds the resolving commit on HEAD by the
   subject the Resolution cites and closes the issue mechanically. `wont-do` is not a
   lane outcome: an issue closed without a change goes straight to `closed` with
   `resolution: wont-do` and `commit: null`.

   **Cite the resolving commit by SUBJECT, in backticks, exactly.** The backfill matches
   it EXACTLY against `git log --format=%s` — no regex, no prefix — so the string in the
   Resolution must be the string you commit with, character for character. Because the
   subject is known before the commit exists, the verify rides IN the resolving commit.
   (`incidents.md` → "The hash that resolved locally".)
2. **Session asset** for any increment with narrative worth keeping — root causes,
   decisions, operator findings triaged, anything the Resolution is too terse to carry:
   `docs/session-assets/YYYY-MM-DD - <author> - <topic>.md`, committed WITH the increment.
   A trivial increment can skip it; say which you did.
3. Commit by explicit path (code + tests + the docs 8a edited + the touched backlog files
   + session asset).
4. **Backlog check — AFTER any rebase, immediately before the push:**

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --check
   ```

   Structural problems, orphaned claims, `commit:` hashes that are not ancestors of HEAD,
   `verified` issues whose cited subject is not on HEAD, `verified` issues without their
   `Docs:` line. The hash rule is exactly what a rebase manufactures, and the subject rule
   can only hold once the resolving commit exists, so it runs after the commit and the
   rebase, not before. A docs-only push has no suite run, which is when this manual check
   is the only thing standing there.
5. **Push the branch first — no OK needed:**

   ```bash
   git -C <worktree> push -u origin <branch>
   ```

   If this machine does not `certifies`, **stop here**: report the branch and the test
   counts, leave the issue at its pre-landing status with Current status saying `⏸ ON
   BRANCH <name>, awaiting the certifying machine`, and do not ask for a landing OK you
   should not be offering.
6. **Land when the lane is verified — per lane, with the operator's OK.** A worktree left
   waiting for closeout is a lane that has not finished. (`incidents.md` → "The batching
   convention broken five times".)
7. **To land — the operator's explicit OK, then RUN it yourself** (their OK is the
   authorization, not a request for a command to paste). The SAFE shape, one command per
   line, each starting with `git`:

   ```bash
   git -C <worktree> fetch origin
   git -C <worktree> merge-base --is-ancestor origin/<main_branch> HEAD   # confirms fast-forward
   git -C <worktree> push origin <branch>:<main_branch>
   ```

   `<branch>:<main_branch>` publishes exactly this branch's commits and cannot sweep
   another session's unpushed work. If origin moved, rebase + retest first (6.1), never
   force. ⚠️ Prefer `git -C <worktree> …` over `cd <worktree> && git …` — a permission
   allow-rule matched as a prefix never matches a `cd` form.

### 10. Clean up

1. Stop the local server **on this lane's port**; confirm the port is free. Do not sweep
   a shared port or the band — another lane may be mid-verification.
2. Remove the worktree — but first verify nothing is lost:

   ```bash
   git -C <worktree> merge-base --is-ancestor HEAD origin/<branch>        # branch pushed
   git -C <worktree> merge-base --is-ancestor HEAD origin/<main_branch>   # or: landed (stronger)
   ```

   Either passing is sufficient; **neither passing means the work exists only on this disk
   — do not remove the worktree.** A worktree held for a verdict can stay in place until
   the lane lands; one still in place is a visible reminder that a lane is waiting.
3. Optionally `git pull --ff-only` the main checkout so it is not left stale (skip if
   another session is active in it — theirs pulls at startup).

## What this skill does NOT cover

- Session startup ceremony — `session-startup`. `session-closeout` still runs at the end
  of the operator's overall session, but do NOT defer this increment's obligations to it:
  the backlog close-out, the session asset and the push all happen in step 9 here.
- Choosing WHICH item to work — that is the operator's assignment.
