# Changelog

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
