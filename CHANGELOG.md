# Changelog

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
