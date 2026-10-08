# lanes

**Claim-gated worktree lanes and a file-based backlog for concurrent agent sessions on one repo.**
A Claude Code plugin. Apache-2.0 · [Privacy policy](https://github.com/kylemullet/lanes/blob/main/README.md#privacy) · [Changelog](CHANGELOG.md)

Several Claude Code sessions (and more than one person) can work one repository at the same
time without colliding, if three things hold: every piece of work is **claimed** before it is
started, every claim is **visible** to every other session and machine, and the rules that make
that safe are **enforced** rather than remembered. `lanes` is those three things, extracted from
a project where they ran for two months across two operators, three machines and a few hundred
closed issues.

## Status

**0.4.11 — complete, pre-release.** Configuration schema, `/lanes:init`, `/lanes:doctor`, the
two backlog scripts, the three protocol skills with their incident references, the
position-guard hook, a marketplace entry, and CI (pytest + `claude plugin validate --strict`).
Installed on two consumers — the project it was extracted from, which runs its backlog gate on
the plugin's scripts, and a solo-mode second adopter. Private until published.

## What it will be

| Layer | What | Where it lives |
| :-- | :-- | :-- |
| **Protocol** — the rule and the incident that produced it | claims as a concurrency primitive with an arbitration rule for ambiguous locks; the backlog as files in git with an integrity gate; the operator-OK gate on *landing*, never on a branch push; assert-position-before-first-edit | ships in the plugin |
| **Binding** — what the rule points at in *this* repo | the test command, the backlog directory, the main branch, who certifies, the port command, the scoped post-rebase re-run | `.claude/lanes/config.toml` |
| **Local fact** — true of one project only | data mirrors, bootstraps, a local server, a scheduled check | three extension-point files beside the config |

## Install

The repo is its own marketplace:

```bash
claude plugin marketplace add kylemullet/lanes
claude plugin install lanes@lanes-marketplace
```

A repo that adopts `lanes` commits `enabledPlugins` and `extraKnownMarketplaces` in its
`.claude/settings.json` (`claude plugin marketplace add … --scope project` and `claude plugin
install … --scope project` write the entries) so the next person opening it is prompted to
install. **Run those from the main clone, never from a worktree** — a project-scope install records
the absolute path it was run from. If the repo ignores `.claude/` wholesale, the rule has to become
`.claude/*` with `!.claude/settings.json` and `!.claude/lanes/`. For hacking on the plugin itself, load a
checkout directly: `claude --plugin-dir /path/to/lanes`.

**Updating: every scope you installed.** Claude Code keeps one install per scope, and
`claude plugin update lanes@lanes-marketplace` updates one of them. A machine with both a user-scope
and a project-scope install needs both, then a restart:

```bash
claude plugin update lanes@lanes-marketplace --scope user
claude plugin update lanes@lanes-marketplace --scope project    # from the main clone
```

Otherwise the session can load the stale copy while the other reads current. `/lanes:doctor`'s `version`
and `marketplace` lines check every install that applies to the repo, and name the one the session runs.

## The hook

`hooks/hooks.json` wires `scripts/guard_position.py` as a `PreToolUse` hook on the four edit
tools. It refuses a write that would land in the **main clone OR on the main branch**, and allows
exactly two shapes: a lane write (neither), and the claim's shape (both, AND a `git.main_direct_paths`
path). The EITHER form matters: the incident behind the hook was a docs write made in the main
clone while another lane's branch was checked out, which an AND form passes. It judges only the
repository the session was started in; a target in another repository is allowed as foreign. It
never sees a write made through Bash, so the skill's two-command position check stays the rule.
`sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" guard_position.py --explain <path>` is the dry run.

**The commit guard** (`scripts/guard_commit.py`) closes that gap at git's own `pre-commit`. It
applies the same truth table to the staged set of every commit, so a file written through Bash, or
a commit made from a terminal, is judged when it is committed. `session-startup` runs
`guard_commit.py --install` every session. That writes a small shim into the repository's hooks
directory, which every worktree shares, so there is no per-clone setup step and a plugin update
re-points it. It never overwrites a `pre-commit` hook it did not write and writes nothing when
`core.hooksPath` is set; `/lanes:doctor` reports both, with the line to add by hand. A shim whose
launcher path has vanished allows the commit and says so, so a stale path cannot block a
repository. `git commit --no-verify` bypasses it once; `git.commit_guard = false` turns it off.
`guard_commit.py --explain` judges the current staged set.

Every hook, command and skill runs its script through `scripts/lanes.sh`, never a bare `python3`. The
launcher takes the first of `$LANES_PYTHON`, `python3`, `python` and `py` that proves it is a real
Python 3.11+, and exits 2 when none does. That matters on Windows, where `python3` can be the Microsoft
Store alias: it exits 49, and a `PreToolUse` hook that exits anything but 2 lets the write through, so a
guard that cannot find Python would otherwise fail open. Set `LANES_PYTHON` to pin the interpreter on a
machine; it is per machine, so it is an environment variable and not a config key.

## Commands

- **`/lanes:init [--force] [--projects CORE,INFRA,DOC]`** — writes `.claude/lanes/config.toml`
  with every key defaulted to **solo mode** and the installed plugin version pinned, plus the
  three extension-point stubs. Never overwrites without `--force`.
- **`/lanes:doctor [--strict] [--json]`** — one line per check: config valid, config tracked,
  every install scope vs the expected version, stubs present, backlog integrity, every `in-progress` claim
  classified (live / setting up / reserved / **stale-claim candidate**), settings pin the plugin (committed AND
  unmodified in the working tree), and this machine's registered marketplace source and installed commit
  match what the repo declares.
  Exit 1 on a failure, or on a warning with `--strict`. **It only reports.** A stale-claim
  candidate is a question for the session that owns the claim or for the operator; the doctor
  never edits an issue file, and a claim younger than the 15-minute floor is never a candidate.
  A marker's kind is read from the start of its bold span, so a paraphrase like
  `**ACTIVE LANE — readlines leg.**` classifies as written. A marker with no kind warns at any age.

- **`/lanes:new <PROJECT> "<title>" [--type=…] [--priority=…] [--assignee=…] [--epic=ID]`** — mints
  an issue the operator is raising: the next free ID, `--reported-by=me` (this machine's operator),
  then the Context written from what they said, so it ends as a filled issue, not a stub. Plain
  prose works too; the command picks the project and title and says so. Session-raised issues
  keep calling `backlog_new.py` directly with `--reported-by=claude`.
- **`/lanes:claim <ID> [<ID> …]`** — claims a slice in one pushed commit (see below).

All are thin: the work is in `scripts/lanes_init.py`, `scripts/lanes_doctor.py`, `scripts/backlog_new.py` and `scripts/lanes_claim.py`, which are
stdlib-only Python (3.11+, for `tomllib`) and run on a machine with no virtualenv.

## The three skills

| Skill | When | What it does |
| :-- | :-- | :-- |
| `session-startup` | "GA", "what's in the queue", any session-opening signal | pull first; identify the operator and machine from the config; run `preflight.md`; close verified issues on the certifying machine; build the exclusion set of in-flight claims; render the Brief (always with a `critical:` line), ask the session mode (or read it from the trigger: `GA quick wins`), offer 2–3 proposals for it; **stop** |
| `worktree-increment` | "do CORE-7", "run the slice", "go" | claim the whole slice up front (`WORKTREE PENDING` / `RESERVED`), one worktree per issue worked sequentially, rebase-then-verify against the baseline, hold for the operator, close the doc loop, push the branch freely, land only with the OK |
| `session-closeout` | "let's wrap", "close out" | sweep every worktree, commit shared text, reconcile the backlog and release this session's unreached claims, run `pre-land.md`, the test gate, rebase, confirm the landing by lane |

Each `SKILL.md` is protocol only; the project-specific steps live in the repo's
`.claude/lanes/{preflight,lane-setup,pre-land}.md`, and the rules' history lives in
`skills/<name>/references/incidents.md`. `tests/test_skills.py` fails if a skill names
the project the protocol was extracted from.

## The backlog scripts

Stdlib-only, run from anywhere inside the repo (or with `--root <repo>`):

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py              # (re)write INDEX.md + index.html (keep both gitignored)
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --check      # exit 1 on any integrity problem
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --report     # aged view for this machine's operator (--who <short>|both)
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --serve      # the HTML view on backlog.view_port, re-parsed per request
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_index.py --backfill [--dry-run] [--commit | --push]
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_new.py CORE "a title" --type=bug --reported-by=<short> [--push]
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" push_guard.py --ok-free [--push] [--add <paths> -m "<subject>"]
```

`backlog_new.py` numbers from the local tree and every ref, after a bounded `git fetch origin`, so an issue
another machine pushed since this clone's last fetch is not handed out again (LANES-4). A failed fetch
warns and numbers from what is here; `--no-fetch` skips it.

`push_guard.py` is the one rule for a push to the main branch that needs no operator OK
(LANES-5). `--ok-free`: every path ahead of `origin/<main>` is under `git.ok_free_paths`
(default: the backlog dir alone), `--check` is green, and no commit edits a claim marker
another machine wrote. `--claim`: every path is main-direct (the claim push's rule). The
backfill close, `backlog_new.py --push`, a staleness fix, the ACTIVE flip and closeout's
release of an unreached claim all go through it; `--add` commits exactly the named paths
first. Exit 0 passed (and pushed) · 1 refused, nothing pushed · 2 passed, push failed.

One for the start of a slice, run in the main clone on the operator's directive (also
`/lanes:claim`):

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_claim.py CORE-64 UI-40 --files "api/x.py, tests/test_x.py"
```

Every ID or none: each must have a file on the main branch and be unclaimed. The first gets
`WORKTREE PENDING`, the rest `RESERVED, NOT STARTED` behind it, in one commit that is checked
and pushed (`--behind <ID>` extends a lane, `--dry-run` prints the markers). A marker names its
owner as `<Short>'s session on <machine id>@<host>`. `--resume <ID>` moves the operator's own
ACTIVE lane to a second machine: it makes the worktree from the pushed branch, re-stamps the
marker to this machine and pushes it. Another person's lane is refused (LANES-7).

And one for the end of a lane, run from its worktree after the operator's landing OK:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_land.py   # land, verify it landed, THEN remove the worktree + branch and close the issue
```

It never cleans up after a landing it cannot read back from the remote: exit 1 means nothing
was pushed, removed or deleted. Once landed it runs `backlog_index.py --backfill --push --isolated`,
so the lane's `verified` issue closes on landing rather than at the next startup. `--isolated`
closes and pushes from a throwaway worktree at a freshly fetched `origin/<main>`, so another
session's unpushed claim in the shared main clone cannot block it, and the main clone itself is
never touched (`--no-close` skips the close; `--keep`, `--dry-run`, `--onto <branch>`).

One file per issue at `<backlog.dir>/<PROJECT>/<ID>-<slug>.md`, flat YAML frontmatter (`id`,
`project`, `type`, `status`, `priority`, `blocked_on`, `assignee`, `reported_by`, `opened`,
`closed`, `commit`, `resolution`, `links`, optional `epic`, and `lane` while claimed) and three H2 sections: Context,
Current status, Resolution. `--check` is the integrity gate: duplicate or misnamed IDs,
out-of-vocabulary values, a `status: in-progress` without its body claim marker (or the
reverse), a `commit:` hash that is not an ancestor of HEAD (the rebase signature), a `verified`
issue whose Resolution does not cite a commit subject on HEAD, a `verified` issue whose change
reached outside `docs_lane_prefixes` without a `Docs:` line, a dangling `epic:` parent, an epic with `status: in-progress`, a
`resolution:` that disagrees with the status, and a lane problem: a `lane:` on an open, blocked
or paused issue (a release deletes it), a value that is not `<ID>@<YYYY-MM-DD>`, or two
ACTIVE/PENDING issues in one lane. The views and `--report` open with **In progress**, one group per
lane named after its slice (`LANES-20/21/9`), its landed issues shown beside the live ones until the
last one lands and the lane disappears. `lanes_claim.py` writes the `lane:` field, which stays on an
issue after it lands; a claim made before it existed is grouped from its ⏳ marker under the same key. `--backfill` closes verified issues by the exact
commit subject their Resolution cites, and only on a machine whose operator row certifies (solo
mode: every machine). The close is deterministic, so several certifying machines may run it at once; `--push`
fetches first, pushes a backlog-only result, and converges on a rejected push by rebasing.

**An epic is never claimed; it reads in progress.** `lanes_claim.py` refuses an epic, and `--check` fails one
marked `in-progress`. Instead, every view derives it: a live epic with a claimed child (or grandchild, through
a nested epic) shows `in-progress` with the lanes doing the work (`▶ lane LANES-1/25/31/27`) in its row and its
roll-up line. Each lane names the epics its issues sit under, and the doctor's claim line names the claim's epic.
Nothing is written to the epic's file, so the state cannot go stale when the lane lands.

## Configuration

`.claude/lanes/config.toml`, **tracked in git** so every operator and machine reads the same
file. Every key is optional. The defaults are solo mode. `templates/config.toml` is the
annotated reference; the short version:

| Key | Default | Meaning |
| :-- | :-- | :-- |
| `plugin_version` | — | the version this repo expects; `/lanes:doctor` warns on drift |
| `backlog.dir` | `docs/backlog` | one file per issue, `<PROJECT>/<ID>-<slug>.md` |
| `backlog.projects` | `["CORE","INFRA","DOC"]` | issue ID prefixes (`INFRA-12`); `[A-Z][A-Z0-9]*` |
| `backlog.types` | story, bug, spike, qa, decision, chore, epic | must include `epic` |
| `backlog.priorities` | critical, high, normal, low | |
| `backlog.docs_lane_prefixes` | = `git.main_direct_paths` | paths whose change can make a doc stale; the `Docs:`-line gate reads it |
| `backlog.claim_marker_exempt` | `[]` | issue IDs whose body legitimately quotes a claim marker |
| `backlog.resolution_required_from` | always | issues closed before this date need no `resolution:` |
| `backlog.view_port` | `8099` | the served backlog view |
| `git.main_branch` | `main` | |
| `git.land_requires_ok` | `true` | the operator-OK gate is on landing, never on a branch push |
| `git.main_direct_paths` | `["docs/", ".claude/lanes/", "*.md"]` | may reach the main branch with no branch and no suite run; the hook's carve-out |
| `git.ok_free_paths` | `[<backlog.dir>/]` | may reach the main branch with no operator OK (`push_guard.py --ok-free`); deliberately narrower than `main_direct_paths` — `[]` makes every main-branch push wait for the OK |
| `tests.command` | `pytest -q` | |
| `tests.required_before_land` | `true` | |
| `tests.rebase_rerun_command` | — | prints the test args for a scoped post-rebase re-run; absent = full suite |
| `worktrees.port_command` | — | prints this lane's localhost port |
| `[[operators]]` | `[]` (solo) | one row per `(git user.name, platform)` — a machine, not a person: `id`, `short`, `certifies`, `may_edit_code`. `id` and the pair are unique; one person on two machines is two rows sharing a `short`. `retired = true` (+ optional `retired_on`) keeps a departed operator's row as history: it grants nothing, never matches a machine, is not offered by `backlog_new.py`, and is valid on closed issues only (and as `reported_by` anywhere) |
| `lanes.code`, `lanes.code_owner` | — | which paths only the owning operator edits; meaningless in solo mode |

**Not configurable, on purpose:** the status vocabulary (`in-progress`, `open`, `blocked`,
`paused`, `verified`, `closed`), the resolution vocabulary (`done`, `duplicate`, `superseded`,
`wont-do`) and the 15-minute claim-age floor. The integrity gate reads them by name; a rename
would break it silently.

### Solo mode

An empty `operators` list means *whoever is here certifies and edits everything*. Every
two-operator rule in the protocol degrades to a no-op, never an error. Fill in `[[operators]]`
only when a second person or machine works the repo; an unknown `(user.name, platform)` pair
in a multi-operator repo resolves to *no permissions*, which the skills treat as "ask, don't
guess".

When someone leaves, mark their row `retired = true` rather than deleting it. Removing it would fail
`--check` on every closed issue that names them. A retired row grants nothing and never matches the
running machine. Its `short` stays valid on closed and verified issues and as `reported_by` (who raised
an issue doesn't change when they leave), but is not offered for new issues. A live issue still
assigned to it fails `--check`, so a departure can't leave live work assigned to someone who is gone.
The doctor's `config` line counts retired rows. With only retired rows left, the repo is in solo mode.

### Extension points

Three files beside the config, each run by one protocol skill when present:

| File | Runs in | After |
| :-- | :-- | :-- |
| `preflight.md` | session startup | the pull, before the queue is read |
| `lane-setup.md` | the worktree flow | `git worktree add` returns |
| `pre-land.md` | session closeout | before the landing OK is requested |

Everything true of one project only goes there, and is deleted from the skills rather than
duplicated.

## Layout

```
lanes/
├── .claude-plugin/     plugin.json, marketplace.json
├── hooks/hooks.json    the position guard (PreToolUse on the edit tools)
├── commands/           init.md, doctor.md, claim.md, new.md
├── skills/             session-startup, worktree-increment, session-closeout (+ references/incidents.md)
├── scripts/            lanes_config.py (loader), lanes_init.py, lanes_doctor.py, backlog_index.py, backlog_new.py, lanes_claim.py, lanes_land.py, push_guard.py, guard_position.py, guard_commit.py, _console.py
├── templates/          config.toml + the three extension-point stubs
├── tests/              pytest, builds throwaway repos
├── CHANGELOG.md · LICENSE · README.md
```

## Roadmap

1. ~~Backlog scripts~~ — shipped in 0.2.0.
2. ~~The three protocol skills~~ — shipped in 0.3.0.
3. ~~The position-guard hook~~ — shipped in 0.4.0.
4. ~~First consumer cut over~~ (0.4.0), then a **second adopter** on a solo-mode config. One
   consumer is a fork with extra steps.
5. ~~`marketplace.json`~~ (0.4.0); ~~`claude plugin validate --strict` in CI~~ (0.4.3).

## Development

```bash
python3 -m pytest -q tests/
claude plugin validate --strict .
claude plugin validate --strict .claude-plugin/plugin.json
claude plugin validate --strict .claude-plugin/marketplace.json
```

CI (`.github/workflows/ci.yml`) runs exactly these on every push. All three are named because which
target descends into `skills/` and `commands/` has differed between machines on the same CLI version.

## Privacy

lanes runs entirely on your machine, inside the repository it is installed in. It reads
`git config user.name` and the platform to pick your row in `.claude/lanes/config.toml`, and the
operator shorts you wrote into that config appear as `assignee` and `reported_by` in the issue files
it creates. The hook reads `CLAUDE_PROJECT_DIR` to know which project it is guarding. Nothing is sent
anywhere: no network calls, no telemetry, no service, no retention. The only outbound action is your
own `git push`, which the skills ask you to authorize before it runs.

## License

Apache-2.0. Copyright 2026 Kyle Mulle.
