# Changelog

## 0.4.30 — the lane row names the slice, not the worktree (2026-10-08)

- **The In progress row drops the worktree and branch names** (LANES-28) in `--report`, `INDEX.md` and
  the HTML card. `LANES-5/7/4/24 · readlines-lanes-4 + lanes-lanes-4 [lanes-4-work]` is now
  `LANES-5/7/4/24 · kyle-mac@… · claimed …`. The names meant nothing to the operator and, once a slice
  moved past its first issue, looked out of step with it. They stay in the ⏳ marker, where the doctor
  reads them as evidence. A lane with no worktree still says so: `worktree pending`, `between issues`,
  `not started`. `lane_label()` returns `phase` (None while an issue is being worked) in place of
  `where` and `branch`.

## 0.4.29 — retired operators (2026-10-08)

- **`retired = true` on an operator row** (plus optional `retired_on = "YYYY-MM-DD"`, LANES-27). A
  departure no longer forces a choice between deleting the row, which fails `--check` on every closed
  issue that names the person, and keeping it live, which still offers them for new work. A retired row:
  - grants nothing (a `certifies` or `may_edit_code` on it is a warning and is ignored) and never
    matches the running machine;
  - is not offered by `backlog_new.py` / `/lanes:new` (`--assignee`, `--reported-by`) or by `--report --who`;
  - validates on history: a closed or verified issue may name any short that is or was an operator,
    and `reported_by` accepts one on any issue, since who raised it doesn't change when they leave;
  - fails `--check` when a live issue is still assigned to it, with a "reassign live work" line.
- The doctor's `config` line counts retired rows (`2 operators + 1 retired (mike-win)`). A repo with only
  retired rows is in solo mode.

## 0.4.28 — the doctor checks every install scope (2026-10-08)

- **`version` reads every `installed_plugins.json` row that applies to the repo** (LANES-25): the
  user scope, plus project or local scope rows whose `projectPath` is this repo's main clone (so a
  worktree session counts the main clone's install). It warns on any row that differs from
  `plugin_version`, gives each its fix line (`claude plugin update lanes@<mkt> --scope <scope>`,
  then restart), and names the copy this session runs. A user-scope 0.4.21 beside a project-scope
  0.4.22 used to read `installed 0.4.22 == expected 0.4.22` while the session loaded 0.4.21.
- **`marketplace` compares every applicable scope's commit** with the marketplace clone's tip,
  instead of the first row it found.
- README: updating means every scope you installed.

## 0.4.27 — an epic reads in progress while a child is claimed (2026-10-08)

- **Derived, never written** (LANES-31). `backlog_index.epic_activity()` maps every live epic that
  has a claimed child, or a claimed child of a nested child epic, to the lanes doing the work.
  `--report`, the served view and `INDEX.md` show that epic as `in-progress`, with
  `▶ lane <slice>` in its row. The report's roll-up line gains `▶ IN PROGRESS: lane …`, the view's
  status pill carries a "derived" tooltip, and its status filter and sort follow the shown state.
  A closed epic keeps its own status.
- **Every lane names its epics** in the In progress block (report, view, INDEX.md), and the
  doctor's claim line ends with ` · epic <ID>`.
- **An epic is never a claim.** `lanes_claim.py` refuses an epic ID, and `--check` fails an epic
  with `status: in-progress`. Hand-marking one would read as a claim with no worktree, and go stale
  the moment the lane landed.

## 0.4.26 — the commit guard: the position rule at git's pre-commit (2026-10-08)

- **New `scripts/guard_commit.py`** (LANES-1). The edit-tool hook never sees a file written
  through Bash or a commit made from a terminal. The commit guard judges the STAGED SET of every
  commit with the same truth table: it refuses a commit on the main branch in the main clone
  that stages a path outside `git.main_direct_paths`, any commit in the main clone off the main
  branch (the incident shape, docs included), and any commit in a worktree that has the main
  branch checked out. A lane commit, and a claim or close on the main branch, pass. A rename
  counts as both its paths. During a rebase it judges the branch being rebased, not the
  detached HEAD.
- **Installed every session, no per-clone step.** `session-startup` step zero runs
  `guard_commit.py --install`, which is idempotent. It writes a `pre-commit` shim into
  `git rev-parse --git-path hooks`, shared by every worktree, and a plugin update re-points
  it. It never overwrites another tool's `pre-commit` and writes nothing under
  `core.hooksPath`; both are reported with the line to add by hand.
- **Fails open only on a stale path.** If the shim's launcher has vanished it allows the commit
  and says so, so a plugin update cannot block every commit in a repository. When no Python
  resolves, the launcher still refuses (LANES-17). `git commit --no-verify` bypasses the guard
  once; `git.commit_guard = false` (new key, default true) turns it off and makes `--install`
  remove the shim.
- **`/lanes:doctor` gains a `commit guard` line**: installed, stale, absent, another tool's hook,
  `core.hooksPath`, or off.

## 0.4.25 — startup asks what kind of session, then proposes 2–3 (2026-10-08)

- **`session-startup` steps 7–8 rewritten** (LANES-24). The five fixed blocks (Brief, view,
  Critical, Quick wins, one Recommended slice) became: the Brief and the view link, the
  **mode question**, then **2–3 proposals for that mode**, then stop. The operator usually
  acted on one block, so most of the analysis went into blocks nobody read, and a single
  slice could only be taken or overruled.
- **Critical is never dropped.** The Brief always carries `critical: N — <ID> …` (or
  `critical: none`), so a mode answer cannot hide a red canary row or a blocker.
- **The menu comes from the operator row**, with no new config key: a row that may edit code
  (and solo mode) gets Critical / unblocking · Quick wins · Deep · Autonomous; a non-code
  operator gets Authoring · Decisions · Quick wins. "Other" takes a project or an epic. A
  mode named in the trigger (`GA quick wins`) skips the question.
- **Autonomous has a rubric** until the backlog grows an `autonomy:` field: no operator
  decision in `blocked_on`, no visual or UX verdict, no legal or product judgment, and
  acceptance criteria a test can check. It also says to keep the machine awake.
- Unchanged: step 5b's exclusion set is built first and binds every proposal in every mode;
  identical titles; startup starts no work; 8a/8b.

## 0.4.24 — issue numbering sees the other machines (2026-10-08)

- **`backlog_new.py` fetches `origin` before it scans the refs** (LANES-4). `git log --all`
  saw only refs this clone had fetched, so an issue another machine pushed since the last
  fetch (a canary bug on its branch, the other operator's new issue) was invisible and its
  number could be minted twice. The fetch is bounded (20s, no credential prompt) and never
  prunes, because a deleted branch's refs keep a renumbered-away ID retired. A failed fetch
  prints one warning and numbers from the refs already here: minting still works offline.
  A clone with no `origin` is not a warning. `--no-fetch` skips the fetch on purpose.

## 0.4.23 — claims carry the machine; a lane can follow its operator (2026-10-08)

- **The doctor judges evidence by machine** (LANES-7). A marker already named its owner
  (`<Short>'s session on <machine id>@<host>`), but the stale-claim check counted "no
  worktree here" against every claim, and `git worktree list` sees one machine only. For a lane
  another machine owns, the pushed branch is now the only evidence. Its lines name the owner,
  and a stale-claim question is addressed to that machine's session. A same-named local
  worktree no longer counts for someone else's lane.
- **`lanes_claim.py --resume <ID>`** re-homes the operator's own ACTIVE lane to this machine. It
  refuses another person's lane, a lane this machine already owns, and a branch origin does
  not have (the branch is the hand-off). It makes the worktree from `origin/<branch>`,
  re-stamps the marker's time and machine (`Resumed from …`), and pushes under the OK-free
  guard.
- **`push_guard.py --ok-free` allows exactly that rewrite**: a marker by the same `short` on
  another machine, replaced in the same file by this machine's marker on the same branch.
  Every other edit to another machine's marker is still refused.
- **Skills:** startup's 5b evidence table splits ACTIVE lanes by owner machine;
  worktree-increment gains step 1r, resuming on another machine.

## 0.4.22 — a backlog-only push needs no OK, behind one guard (2026-10-07)

- **`scripts/push_guard.py`** (LANES-5). The claim push and the backfill close each carried
  their own copy of the "may this reach main without an OK" rule; every other backlog write
  (a staleness fix, a released claim, an issue minted mid-session) waited for the next OK'd
  push, invisible to other machines until then. One guard, two modes: `--ok-free` (every path
  ahead of origin under `git.ok_free_paths`, `--check` green, no commit edits a claim marker
  another machine wrote) and `--claim` (every path main-direct, unchanged). `--push` pushes and
  converges on a rejection by rebasing; `--add <paths> -m <subject>` commits exactly those
  paths first. `lanes_claim.py` and `backlog_index.py --backfill --push` now call it.
- **`git.ok_free_paths`**, default `[<backlog.dir>/]`. Deliberately not `main_direct_paths`:
  the standing docs change rules every session treats as ground truth, so they keep the OK.
  `[]` restores "every main-branch push waits for an OK".
- **The claim-marker check sees machines, not sessions.** A marker names
  `<Short>'s session on <machine>@<host>`; an edit to one naming another machine is refused.
  Two sessions on one machine share the id, so that half of "never write to another
  session's claim" stays a prohibition in the skills.
- **`backlog_new.py --push`** commits the minted issue alone and publishes it; refused from a
  lane worktree before anything is minted. **`/lanes:new`** publishes after writing the
  Context, through `push_guard.py --add`, in the main clone only.
- **Skills:** the branch-policy sections name the rule once; startup's staleness fix,
  worktree-increment's ACTIVE flip and closeout's release of unreached claims publish through
  the guard. The backfill close's guard skips the `--check` leg: a SKIPPED verified issue
  leaves `--check` red and must not hold back the closes that are right.

## 0.4.21 — /lanes:new mints an issue the operator raises (2026-10-07)

- **`/lanes:new`** (LANES-2). It runs `backlog_new.py` through the launcher, then reads the
  minted file back and writes its Context from what the operator said, so it ends as a filled
  issue rather than a stub. It takes the script's form (`<PROJECT> "<title>" [options]`) or plain
  prose; for prose it picks the project and title, says which, and asks when no project fits.
  It never commits or pushes. `allowed-tools` pre-approves exactly that one script.
- **`backlog_new.py --reported-by=me`** resolves to this machine's operator short. It is
  explicit, not a default, so the "no default reporter" rule holds. A machine with no
  operator row in a multi-operator repo is refused rather than guessed. `/lanes:new` passes
  it; a session raising an issue on its own still passes `--reported-by=claude`.

## 0.4.20 — the doctor reads a paraphrased claim kind, and warns on a missing one at once (2026-10-07)

- **The kind opens the bold span** (LANES-19). `lanes_doctor.py` read a claim's kind only when
  it was the whole bold span (`**ACTIVE LANE.**`), so paraphrased markers like
  `**ACTIVE LANE — readlines leg.**` or `**RESERVED, NOT STARTED — queued behind LANES-3**`
  read as kind-less. The views' marker parser already accepted them, so the two disagreed. The
  doctor now matches the kind as the span's prefix, the way the views do.
- **A kind-less marker warns at any age.** It used to pass under the 15-minute floor as "live
  by rule" and warn only at minute 15. A marker is written whole, kind included, so a young one
  without a kind is a misspelling, not a lane still setting up.
- The templates stay exact. `KIND_TEMPLATE_RE` keeps the old spelling, and `test_skills.py`
  holds the skills' markers to it, so the leniency applies only to reading.

## 0.4.19 — the landing's close runs off origin, past a busy main clone (2026-10-07)

- **`backlog_index.py --backfill --push --isolated`** (LANES-23). Closes and pushes from a
  throwaway worktree detached at a freshly fetched `origin/<main>`, then removes it. The main
  clone's branch, index and files are never touched, so another session's claim, committed
  there and not yet pushed, no longer makes the close refuse on the divergence. That refusal is
  what the first real `lanes_land.py` landing hit. A close that cannot push is discarded with
  the worktree; it is deterministic, so the next backfill redoes it. `--isolated` without
  `--push` is refused.
- **`lanes_land.py` closes with `--isolated`.** The main clone no longer fast-forwards to the
  close as part of the landing; it shows the close at its next pull. `worktree-increment` 9.7
  (and its by-hand form) and the README say so.
- Startup and closeout keep the in-place `--backfill --push`. Startup runs it right after its
  own pull so everything downstream reads the closed state, and closeout runs it in a clone
  it has just reconciled.

## 0.4.18 — lanes are recorded, named after their slice, and checked (2026-10-07)

- **`lane:` frontmatter** (LANES-10). `lanes_claim.py` writes `lane: <lead-ID>@<YYYY-MM-DD>` on
  every issue of a slice, and a `--behind` extension copies the extended lane's value. Behind a
  claim made before the field existed it derives the key the views derive from the marker
  (`<ID>@<claim date>`), so old and new claims group as one lane. The field STAYS on an issue
  that lands, as the record of which lane resolved it; closeout's release (and a partial going
  back to the queue) deletes it with the ⏳ marker.
- **A lane stays whole until its last issue lands** (Kyle). Its landed issues show beside the live
  ones (✓ landed / ✓ closed, full titles, landed first), and the lane disappears from the views
  only when none of its issues is in progress.
- **A lane is named after its slice**: `LANES-20/21/9`, the lead's full ID then the others'
  numbers in slice order (`LANES-22/INFRA-100` across projects). The lead comes from the
  recorded key, so the name holds after the lead lands and only reservations remain. The
  worktree and branch move into the card's detail line.
- **`--report` and `INDEX.md` open with In progress**, grouped by lane like the HTML view, and a
  claimed issue is listed once, under its lane, not again in the queue. `session-startup`
  block I lists in-flight work one line per lane.
- **`--check` lane rules**: a `lane:` on an open, blocked or paused issue, a value that is not
  `<ID>@<YYYY-MM-DD>`, or two ACTIVE/PENDING issues in one lane. A lane with none is legal
  (between two issues of a slice), and so is an in-progress issue without the field: claims
  made before 0.4.18 are grouped from their markers, and only the owning session may write to
  a claim.
- The view's card is named from the lane's ACTIVE/PENDING issue rather than its first one, so
  a slice whose lead has landed shows where work actually is.

## 0.4.17 — the backlog view, redesigned, with lanes on top (2026-10-07)

- The view (`index.html` and `--serve`) is laid out again (LANES-22).
  - **In progress, grouped by lane, at the top.** One card per lane: worktree, branch, machine,
    how long ago it was claimed, then its issues in slice order as active / pending / reserved.
    Lanes are read from the ⏳ claim markers (`queued behind <ID>` joins a reservation to its lead).
    A reservation whose lead is no longer claimed says so. A claimed issue appears once, in its
    card, not again in the queue. This is LANES-10's view half; its `lane:` field follows LANES-9.
  - **Title is the second column**, and blocked-on sits under it on one clamped line with the full
    text on hover. It no longer gets a column that wrapped rows to nine lines. `Opened` left the
    live table; `Age` sorts the same way.
  - **The filters fold behind a `Filters` button** with a count of active filters, and the chosen
    open/closed state is remembered per browser. Project chips show live counts.
  - **A one-line header** with stat tiles (live, in progress, critical, verified, closed). The
    generated-file note moves to a footer. On `--serve`, the clone position sits in the header when
    level and becomes a callout when behind.
  - **Backlog problems are a collapsed callout**, one per line, in the file view too. Before, they
    were one paragraph, and only on `--serve`.
  - Designed for light and dark, and for a phone: secondary columns drop below 720px and the page
    never scrolls sideways.
- Fix: a repo with no epics no longer hides every row. The epic filter now passes when no epic
  row of chips exists.

## 0.4.15 — a lane's issue closes when it lands (2026-10-07)

- `lanes_land.py` closes the issue it just landed (LANES-21). After the landing reads back and the
  clean-up, it runs `backlog_index.py --backfill --push` in the main clone. The resolving hash is
  final at that point, so `verified` no longer waits a whole session for the next startup. The
  backfill's own guards hold: it fast-forwards first, refuses off the main branch, and pushes only
  backlog-only commits. A close that cannot push exits 2 and is left to startup. `--no-close` skips
  it, and nothing runs for `--onto` another branch.
- `session-closeout` step 2 sweeps `--backfill --push` (or `--commit`, where a backlog-only push
  needs an OK) for lanes landed by hand or by another session. `session-startup` step 2d is the
  backstop.
- All three skills: housekeeping that needs no OK (the backfill, branch and claim pushes) is done and
  reported, never offered as a question.

## 0.4.14 — land, verify, then clean up (2026-10-07)

- New `scripts/lanes_land.py`: `worktree-increment` step 9.7's landing and step 10's clean-up as
  one operation (LANES-20). It refuses, touching nothing, from the main clone, on the main branch,
  with a dirty tree or on a machine that does not certify. It checks the fast-forward, pushes
  `<branch>:<main>`, re-fetches and requires HEAD on `origin/<main>`, and only then removes the
  worktree and deletes the branch, locally and on origin. The remote branch is kept if it carries
  commits that did not land. Exit 1 = not landed, nothing changed; 2 = landed, a named clean-up
  step left. `--keep`, `--dry-run`, and `--onto <branch>` for a repo that integrates on a branch
  other than `git.main_branch`.
- A session had run the landing and the clean-up on one line joined by `;`. The fast-forward lost a
  race with another session's push, nothing landed, and the clean-up deleted the worktree and the
  branch on both sides anyway.
- `worktree-increment` step 10: a branch, local or remote, is deleted only after it has **landed**,
  never because it was pushed. The landing and the clean-up are never one command line. The
  recovery path (`git fsck --unreachable --no-reflogs`) is in the incident.
- `session-closeout` step 3 carries the same branch rule.

## 0.4.16 — claim the slice mechanically (2026-10-07)

- New `scripts/lanes_claim.py` and `/lanes:claim`: `session-startup` 8b and `worktree-increment`
  step 1's claim as one all-or-nothing operation (LANES-9). It fetches and fast-forwards the main
  clone, then refuses unless every named ID has a file on `origin/<main>`. A missing ID is named
  with the refs where it does exist. It also refuses any ID that is `in-progress`, `verified`,
  `closed` or has uncommitted changes. It writes `status: in-progress` and the marker on every ID:
  the first `WORKTREE PENDING` with `--files`, each later one `RESERVED, NOT STARTED` behind the
  one before. Timestamps are local, the spelling is exactly what the doctor reads, and a prior
  `blocked`/`paused` status is noted. Then it runs `--check`, makes one commit by explicit path,
  applies the main-direct guard and pushes. A rejected push rebases; a concurrent change to one of
  the claimed issues withdraws the claim. `--behind <ID>` extends a lane, `--dry-run` prints the
  markers. Exit 1 = nothing written, 2 = committed but not pushed.
- `session-startup` 8b and `worktree-increment` step 1 call it instead of describing the edit. The
  startup skill's own example of the RESERVED marker misspelled it for the doctor, and a session
  copied it; that example is gone.

## 0.4.15 — a lane's issue closes when it lands (2026-10-07)

- `lanes_land.py` closes the issue it just landed (LANES-21). After the landing reads back and the
  clean-up, it runs `backlog_index.py --backfill --push` in the main clone. The resolving hash is
  final at that point, so `verified` no longer waits a whole session for the next startup. The
  backfill's own guards hold: it fast-forwards first, refuses off the main branch, and pushes only
  backlog-only commits. A close that cannot push exits 2 and is left to startup. `--no-close` skips
  it, and nothing runs for `--onto` another branch.
- `session-closeout` step 2 sweeps `--backfill --push` (or `--commit`, where a backlog-only push
  needs an OK) for lanes landed by hand or by another session. `session-startup` step 2d is the
  backstop.
- All three skills: housekeeping that needs no OK (the backfill, branch and claim pushes) is done and
  reported, never offered as a question.

## 0.4.14 — land, verify, then clean up (2026-10-07)

- New `scripts/lanes_land.py`: `worktree-increment` step 9.7's landing and step 10's clean-up as
  one operation (LANES-20). It refuses, touching nothing, from the main clone, on the main branch,
  with a dirty tree or on a machine that does not certify. It checks the fast-forward, pushes
  `<branch>:<main>`, re-fetches and requires HEAD on `origin/<main>`, and only then removes the
  worktree and deletes the branch, locally and on origin. The remote branch is kept if it carries
  commits that did not land. Exit 1 = not landed, nothing changed; 2 = landed, a named clean-up
  step left. `--keep`, `--dry-run`, and `--onto <branch>` for a repo that integrates on a branch
  other than `git.main_branch`.
- A session had run the landing and the clean-up on one line joined by `;`. The fast-forward lost a
  race with another session's push, nothing landed, and the clean-up deleted the worktree and the
  branch on both sides anyway.
- `worktree-increment` step 10: a branch, local or remote, is deleted only after it has **landed**,
  never because it was pushed. The landing and the clean-up are never one command line. The
  recovery path (`git fsck --unreachable --no-reflogs`) is in the incident.
- `session-closeout` step 3 carries the same branch rule.

## 0.4.13 — doctor checks the settings file and the marketplace source (2026-10-07)

- The single `settings` check is now three (LANES-16).
  - `settings` warns when the tracked `.claude/settings.json` differs from HEAD.
    `claude plugin marketplace remove` empties it, and the old check caught that only when the edit
    happened to remove `enabledPlugins`.
  - `settings lanes` checks that lanes is enabled and its marketplace declared, in HEAD as well as in
    the working tree. A committed regression is reported as committed.
  - `marketplace` compares this machine's registered source (repo, ref) with the declared one, and
    the installed commit with the marketplace clone's tip. No fetch is made. This is what would have
    flagged a machine still installing from `main` after the repo moved to `next`.
- The doctor now reads Claude Code's plugin state: `LANES_PLUGINS_DIR` if set, else the directory
  above the plugin's own cache path, else `$CLAUDE_CONFIG_DIR/plugins`, else `~/.claude/plugins`.

## 0.4.12 — backfill on concurrent certifying machines (2026-10-07)

- `--backfill` closes deterministically. `closed:` is the resolving commit's committer date
  (it used to be the day the backfill ran), and `commit:` is a fixed 7-character abbreviation
  (git's default length scales with each clone's object count). Two machines closing the same
  issue now write byte-identical files (LANES-6).
- New `--backfill --push`. It fetches and fast-forwards the main branch before scanning, commits,
  and pushes, but only when every commit ahead of origin touches the backlog dir alone. On a
  rejected push it re-fetches and rebases: an identical close merges cleanly or drops out, a real
  conflict aborts the rebase and leaves the commit local. It never forces. Several certifying
  machines may run it at once, so no machine has to be named the single writer.

## 0.4.11 — one person, two machines (2026-10-07)

- Operator rows may share a `short`. A row is a machine (`id` and the `(name, platform)` pair stay
  unique); `short` is the person, so one person on two machines is two rows with one short. 0.4.10
  and earlier rejected that as a duplicate, which left a second machine with no permissions or a
  fake second assignee. Assignees, reporters, the certifier label and the default assignee list each
  person once (LANES-3).

## 0.4.10 — fail closed without a working Python (2026-10-07)

- Every hook, command and skill runs its script through the new `scripts/lanes.sh`, never a bare
  `python3`. On Windows `python3` can be the Microsoft Store alias, which exits 49; for a `PreToolUse`
  hook any exit but 2 allows the call, so the position guard failed **open** on such a machine, and a
  missing `python3` (127 / 9009) failed open the same way. The launcher takes the first of
  `$LANES_PYTHON`, `python3`, `python`, `py` that proves it is Python 3.11+ (the scripts need
  `tomllib`), and exits **2** when none does. A set `LANES_PYTHON` that does not work is an error,
  never silently replaced. It runs only a script in its own directory.
- The hook command ends `|| exit 2`: if `sh` itself is missing, or the guard crashes, the write is
  blocked rather than allowed.
- `commands/doctor.md` and `commands/init.md` pre-approve the launcher form of their one script.
- `tests/test_ci.py` follows `ci.yml`'s `branches: [main, next]`.

## 0.4.9 — listing links (2026-10-04)

- README gains a Privacy section: what is read (`git config user.name`, the platform, the repo's own
  lanes config, `CLAUDE_PROJECT_DIR`), and that nothing leaves the machine.
- CI runs on pushes to `main` and on pull requests, not on tag pushes: a release tag points at a commit
  `main` has already run, so every `claude plugin tag --push` was buying a second identical run.
- `plugin.json` carries `homepage` and `repository` so the directory listing has somewhere to point.
  The form also suggests `documentationUrl` and `supportUrl`, but `claude plugin validate --strict`
  (2.1.289) rejects both as unknown fields, so they stay out until the CLI's schema knows them.

## 0.4.8 — directory review, third pass (2026-10-04)

- `guard_position.py` reads each of its eight variables by literal name; the previous loop over a tuple
  read as "a variable named at run time".
- `session-closeout` 1b: the per-worktree checks are written with the skills' `<placeholder>` convention,
  no shell variables; the directory reads any `$` in a skill's command as a command assembled at run time.

## 0.4.7 — directory review, second pass (2026-10-04)

- `guard_position.py` reads the eight variables it needs by name (`os.getenv`), never the whole
  environment: the directory read a whole-environment enumeration beside a runtime-assembled shell line in
  `session-closeout` as "a credential leaving the machine in two steps". Neither half ever did that; now
  neither half is there.
- `session-closeout` 1b: the worktree sweep pipes `git worktree list` into `while read`, no `$(...)`.
- No file names the icon by path (the directory holds a plugin whose text references an image an
  interpreter could be pointed at). The size-band test went with it; the directory enforces that band.

## 0.4.6 — the icon (2026-10-04)

- The listing icon: a trunk that becomes the arrow, two lanes that leave it and rejoin it at
  different heights, and a third that ends in a square — drawn as outlines, amber on dark. The vector
  source is `assets/icon.svg`; the PNG is rendered from it at 1024 px.

## 0.4.5 — first directory submission (2026-10-04)

- The hook command ends `|| exit 2`: if `sh` itself is missing, or the guard crashes, the write is
  blocked rather than allowed.
- `commands/doctor.md` and `commands/init.md` pre-approve exactly the script each runs
  (`Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<script>":*)`), not every `python3` command — the
  directory's policy check held the broad form.
- `userConfig.worktree_root` removed from the manifest: declared since 0.4.0, read by nothing, and the
  directory's credential check reads a declared-but-unused option as a hand-off. A key returns the day
  a script reads it.
- A listing icon (1024 px): the directory fixes it at the first submission, so it ships before one.
  `tests/test_listing.py` pins the first two.

## 0.4.4 — CI green (2026-10-04)

- Frontmatter is now strict YAML: `worktree-increment`'s description carried a `: ` ("the full
  lifecycle: claim → …") and both commands' `argument-hint` began with `[`, which a strict parser reads
  as a flow sequence. The runtime tolerated all three; `claude plugin validate --strict` in CI did not,
  while the same CLI version on the author's machine never descended into the components. Values quoted.
- `tests/test_skills.py::test_plugin_validates_strict` skipped on the wrong signal: a missing executable
  is a `FileNotFoundError`, not "command not found" on stderr. Now `shutil.which`. The pytest job installs
  the CLI so CI runs the test instead of skipping it.
- The validator targets are the repo root and the two manifests. A bare `skills` / `commands`
  directory is read as a plugin root on the runner ("No manifest found"), and which target descends
  into the components differs between machines on the same CLI version; the three named cover it.

## 0.4.3 — CI (2026-10-04)

- `.github/workflows/ci.yml`: pytest plus `claude plugin validate --strict` on every push and pull
  request. The validator is run once per target (`plugin.json`, `marketplace.json`, `skills/`,
  `commands/`): on the author's machine a run on the repo root checked only the marketplace manifest,
  so each target is named rather than trusting how a given build resolves a directory. `tests/test_ci.py`
  pins the shape.
- The first consumer retires its own copies of `backlog_index.py` / `backlog_new.py` the same day
  (its INFRA-67); its CI checks this repo out and runs the plugin's `--check --root .`.

## 0.4.2 — second-adopter fixes, continued (2026-10-04)

- `/lanes:init` and `/lanes:doctor` name the exact gitignore shape when `.claude/` is excluded
  wholesale: `.claude/*` plus `!.claude/settings.json` and `!.claude/lanes/` — git cannot re-include a
  file whose parent directory is excluded, which the first wording did not say.
- README: install from the main clone, never from a worktree (a project-scope install records the
  absolute path it was run from).

## 0.4.1 — second-adopter fixes (2026-10-04)

- `git.main_direct_paths` defaults to `["docs/", ".claude/lanes/", "*.md"]`. Found on the second
  adopter: with the lanes directory outside the default list, adopting the plugin was itself a
  write the position guard refuses in the main clone, so the first lane had to be the adoption.
  The lanes files are process docs; they belong with `docs/`.
- `/lanes:doctor` gains a `views` check: the generated `INDEX.md` / `index.html` must be gitignored
  (the second adopter had no such rule).
- `/lanes:init` keeps warning when `.claude/` is gitignored wholesale (the second adopter's case);
  the fix it names is two negation rules (`!.claude/settings.json`, `!.claude/lanes/`).

## 0.4.0 — the hook and the marketplace (2026-10-04)

- `hooks/hooks.json` + `scripts/guard_position.py` — the position guard as a `PreToolUse` hook on
  `Write|Edit|MultiEdit|NotebookEdit`: refuses a write that would land in the main clone OR on the
  main branch, allows exactly the lane shape and the claim shape. `git.main_branch` and
  `git.main_direct_paths` are read from the TARGET repo's `.claude/lanes/config.toml` (defaults
  otherwise). **Scoped to the repo the session started in** (`$CLAUDE_PROJECT_DIR`): a write into a
  different repository is allowed as foreign — the first consumer's copy refused every write into
  this plugin's own repo while the plugin was being built from a session there.
- `.claude-plugin/marketplace.json` — the repo doubles as its own marketplace (`"source": "."`):
  `claude plugin marketplace add <owner>/lanes` then `claude plugin install lanes@lanes-marketplace`.
- `tests/test_guard_position.py` — truth table through a fake environment, the hook contract,
  config binding, the foreign-repo rule, and the real git path with a second repository.

## 0.3.0 — the protocol skills (2026-10-04)

- `skills/session-startup`, `skills/worktree-increment`, `skills/session-closeout` — the three
  skills, layer-separated: protocol in `SKILL.md`, bindings read from the config
  (`git.main_branch`, `backlog.dir`, `tests.command`, `tests.rebase_rerun_command`,
  `worktrees.port_command`, `operators[]`, `lanes.*`), local facts delegated to the three
  extension points (`preflight.md` after the pull, `lane-setup.md` after `git worktree add`,
  `pre-land.md` before the landing OK). Every two-operator step says what solo mode does.
- `skills/*/references/incidents.md` — every rule's incident, dated, operators anonymized to roles,
  mechanics kept.
- `tests/test_skills.py` — the portability gate: no name of the source project, its people, its
  machines or its local tooling may appear in a skill; marker vocabulary agrees with the doctor.

## 0.2.0 — the tracker (2026-10-04)

- `scripts/backlog_index.py` — the file-based backlog: local views (`INDEX.md` + sortable
  `index.html`), `--report`, `--check` (structure, claim/marker agreement, commit-citation
  ancestry, verified-issue resolvability, the `Docs:`-line doc-loop gate, epic parents,
  resolution/status agreement), `--backfill` (close verified issues by the commit subject they
  cite; refused on a machine whose operator row does not certify), `--serve` (re-parses on every
  request). Every table it reads comes from the config, resolved once at import into module
  globals; `--root` points it at another repository.
- `scripts/backlog_new.py` — mint an issue with the next free ID across the local tree AND every
  ref (two worktrees cannot mint the same number); enums from the config; `--reported-by` required.
- `/lanes:doctor` now runs `backlog_index.py --check` whenever the backlog directory exists.
- Config: `backlog.docs_lane_prefixes` entries are a directory prefix (`docs/`), a root glob
  (`*.md`) or an exact path; `backlog.resolution_required_from` omitted means always required.
- Dropped from the source project's copies, not ported: the positional-queue cutover artifacts
  (`_review`, `owner:`, `legacy_ref`), hard-coded operator names, the port-constant import.

## 0.1.0 — skeleton (2026-10-03)

- `.claude-plugin/plugin.json` manifest.
- Config schema: `.claude/lanes/config.toml`, every key optional, defaults mean **solo mode**.
  Loader in `scripts/lanes_config.py` (stdlib only, `tomllib`, Python 3.11+).
- `/lanes:init` — scaffolds `config.toml` + the three extension-point stubs
  (`preflight.md`, `lane-setup.md`, `pre-land.md`).
- `/lanes:doctor` — config valid, installed vs expected plugin version, extension-point
  files present, backlog `--check` (when the tracker ships), stale-claim candidates older
  than the 15-minute floor (reported as questions, never edited).
- Not yet in this version: the backlog scripts, the three protocol skills, the position-guard
  hook, `marketplace.json`. See README → Roadmap.
