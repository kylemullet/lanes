---
description: Scaffold .claude/lanes/config.toml (solo-mode defaults) and the three extension-point stubs in this repo
argument-hint: [--force] [--projects CORE,INFRA,DOC]
allowed-tools: Bash(python3:*), Read
---

Initialize the `lanes` protocol for the repository the session is in.

1. Run, exactly:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lanes_init.py" $ARGUMENTS
   ```

   It writes `.claude/lanes/config.toml` with every key defaulted to solo mode, and the
   three extension-point stubs `preflight.md`, `lane-setup.md`, `pre-land.md` beside it.
   It never overwrites an existing file unless `--force` was passed; it says which files
   it wrote and which it left alone.

2. Read the generated `config.toml` back and tell the user, in a few lines:
   - the mode it is in (solo, or how many operators are listed),
   - the `backlog.projects` prefixes it chose,
   - the three keys most worth checking for this project: `git.main_branch`,
     `tests.command`, `git.main_direct_paths`.

3. If the repository has more than one person or machine working it, say that the
   `[[operators]]` table in the file is where the second one goes, and that solo mode
   is the default until it is filled in.

4. Finish by suggesting `/lanes:doctor` to confirm the result. Do not edit the config
   yourself unless the user asks; the file is theirs.
