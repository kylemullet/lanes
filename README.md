# lanes

**Claim-gated worktree lanes and a file-based backlog for concurrent agent sessions on one repo.**
A Claude Code plugin.

Several Claude Code sessions (and more than one person) can work one repository at the same
time without colliding, if three things hold: every piece of work is **claimed** before it is
started, every claim is **visible** to every other session and machine, and the rules that make
that safe are **enforced** rather than remembered. `lanes` is those three things, extracted from
a project where they ran for two months across two operators, three machines and a few hundred
closed issues.

## Status

**0.2.0 — the tracker.** The configuration schema, `/lanes:init`, `/lanes:doctor`, and the
two backlog scripts (`backlog_index.py`, `backlog_new.py`) with their tables read from the
config. The protocol skills and the position-guard hook are being extracted next (see
Roadmap). Nothing here is stable yet.

## What it will be

| Layer | What | Where it lives |
| :-- | :-- | :-- |
| **Protocol** — the rule and the incident that produced it | claims as a concurrency primitive with an arbitration rule for ambiguous locks; the backlog as files in git with an integrity gate; the operator-OK gate on *landing*, never on a branch push; assert-position-before-first-edit | ships in the plugin |
| **Binding** — what the rule points at in *this* repo | the test command, the backlog directory, the main branch, who certifies, the port command, the scoped post-rebase re-run | `.claude/lanes/config.toml` |
| **Local fact** — true of one project only | data mirrors, bootstraps, a local server, a scheduled check | three extension-point files beside the config |

## Install

Local development, from a clone:

```bash
claude --plugin-dir /path/to/lanes
```

A marketplace entry is on the roadmap. A repo that adopts `lanes` commits `enabledPlugins` and
`extraKnownMarketplaces` in `.claude/settings.json` so the next person is prompted to install.

## Commands

- **`/lanes:init [--force] [--projects CORE,INFRA,DOC]`** — writes `.claude/lanes/config.toml`
  with every key defaulted to **solo mode** and the installed plugin version pinned, plus the
  three extension-point stubs. Never overwrites without `--force`.
- **`/lanes:doctor [--strict] [--json]`** — one line per check: config valid, config tracked,
  installed vs expected version, stubs present, backlog integrity, every `in-progress` claim
  classified (live / setting up / reserved / **stale-claim candidate**), settings pin the plugin.
  Exit 1 on a failure, or on a warning with `--strict`. **It only reports.** A stale-claim
  candidate is a question for the session that owns the claim or for the operator; the doctor
  never edits an issue file, and a claim younger than the 15-minute floor is never a candidate.

Both are thin: the work is in `scripts/lanes_init.py` and `scripts/lanes_doctor.py`, which are
stdlib-only Python (3.11+, for `tomllib`) and run on a machine with no virtualenv.

## The backlog scripts

Stdlib-only, run from anywhere inside the repo (or with `--root <repo>`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py"              # (re)write INDEX.md + index.html (keep both gitignored)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py" --check      # exit 1 on any integrity problem
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py" --report     # aged view for this machine's operator (--who <short>|both)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py" --serve      # the HTML view on backlog.view_port, re-parsed per request
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_index.py" --backfill [--dry-run] [--commit]
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/backlog_new.py" CORE "a title" --type=bug --reported-by=<short>
```

One file per issue at `<backlog.dir>/<PROJECT>/<ID>-<slug>.md`, flat YAML frontmatter (`id`,
`project`, `type`, `status`, `priority`, `blocked_on`, `assignee`, `reported_by`, `opened`,
`closed`, `commit`, `resolution`, `links`, optional `epic`) and three H2 sections: Context,
Current status, Resolution. `--check` is the integrity gate: duplicate or misnamed IDs,
out-of-vocabulary values, a `status: in-progress` without its body claim marker (or the
reverse), a `commit:` hash that is not an ancestor of HEAD (the rebase signature), a `verified`
issue whose Resolution does not cite a commit subject on HEAD, a `verified` issue whose change
reached outside `docs_lane_prefixes` without a `Docs:` line, a dangling `epic:` parent, and a
`resolution:` that disagrees with the status. `--backfill` closes verified issues by the exact
commit subject their Resolution cites, and only on a machine whose operator row certifies (solo
mode: every machine).

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
| `git.main_direct_paths` | `["docs/", "*.md"]` | may reach the main branch with no branch and no suite run; the hook's carve-out |
| `tests.command` | `pytest -q` | |
| `tests.required_before_land` | `true` | |
| `tests.rebase_rerun_command` | — | prints the test args for a scoped post-rebase re-run; absent = full suite |
| `worktrees.port_command` | — | prints this lane's localhost port |
| `[[operators]]` | `[]` (solo) | one row per `(git user.name, platform)` — a machine, not a person: `id`, `short`, `certifies`, `may_edit_code` |
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
├── .claude-plugin/plugin.json
├── commands/           init.md, doctor.md
├── scripts/            lanes_config.py (loader), lanes_init.py, lanes_doctor.py, backlog_index.py, backlog_new.py, _console.py
├── templates/          config.toml + the three extension-point stubs
├── tests/              pytest, builds throwaway repos
├── CHANGELOG.md · LICENSE · README.md
```

## Roadmap

1. ~~Backlog scripts~~ — shipped in 0.2.0.
2. **The three protocol skills** — `session-startup`, `worktree-increment`,
   `session-closeout` — layer-separated: protocol in the skill, bindings from the config,
   local facts in the extension points. Every incident citation kept, with its date.
3. **The position-guard hook** — a `PreToolUse` hook on the edit tools that refuses a write
   landing in the main clone *or* on the main branch, with the claim's shape as the only
   carve-out.
4. **First consumer cut over**, then a **second adopter** on a solo-mode config. One consumer
   is a fork with extra steps.
5. `marketplace.json` and `claude plugin validate --strict` in CI.

## Development

```bash
python3 -m pytest -q tests/
claude plugin validate --strict .
```

## License

Apache-2.0. Copyright 2026 Kyle Mulle.
