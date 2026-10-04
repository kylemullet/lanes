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

**0.1.0 — skeleton.** This version ships the configuration schema, `/lanes:init` and
`/lanes:doctor`. The protocol skills, the backlog scripts and the position-guard hook are
being extracted next (see Roadmap). Nothing here is stable yet.

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
├── scripts/            lanes_config.py (loader), lanes_init.py, lanes_doctor.py, _console.py
├── templates/          config.toml + the three extension-point stubs
├── tests/              pytest, builds throwaway repos
├── CHANGELOG.md · LICENSE · README.md
```

## Roadmap

1. **Backlog scripts** — `backlog_index.py` (`--check`, index, `--report`, `--backfill`,
   `--serve`) and `backlog_new.py`, with their tables read from the config.
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
