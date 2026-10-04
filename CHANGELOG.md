# Changelog

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
