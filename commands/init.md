---
description: Set up lanes in this repo — config (solo-mode defaults), the three extension-point stubs, the backlog folder, the settings.json declaration and the git hooks
argument-hint: "[--force] [--projects CORE,INFRA,DOC]"
allowed-tools: 'Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_init.py:*), Read'
---

Initialize the `lanes` protocol for the repository the session is in.

1. Run, exactly:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_init.py $ARGUMENTS
   ```

   It sets up everything `/lanes:doctor` checks:
   - `.claude/lanes/config.toml` with every key defaulted to solo mode, and the three
     extension-point stubs `preflight.md`, `lane-setup.md`, `pre-land.md` beside it;
   - the backlog folder (`backlog.dir`) with a `README.md`, and a `.gitignore` there for
     the two generated views unless they are ignored already;
   - lanes declared in `.claude/settings.json`, from the marketplace this machine
     installed it from, so the next person is prompted to install it. It only adds to an
     existing file and never overwrites one;
   - the view hooks and the commit guard in `.git/hooks`. The guard is held back while a
     file init wrote is uncommitted and outside `git.main_direct_paths` (by default,
     `.claude/settings.json`), because it would refuse that very commit.

   It never overwrites an existing file unless `--force` was passed. It says which files
   it wrote, updated and left alone, and prints the `git add` for what needs committing.

2. Read the generated `config.toml` back and tell the user, in a few lines:
   - the mode it is in (solo, or how many operators are listed),
   - the `backlog.projects` prefixes it chose,
   - the three keys most worth checking for this project: `git.main_branch`,
     `tests.command`, `git.main_direct_paths`.

3. If the repository has more than one person or machine working it, say that the
   `[[operators]]` table in the file is where the second one goes, and that solo mode
   is the default until it is filled in.

4. Pass on any `WARN` line as it was printed. Give the user the `git add` and
   `git commit` the script printed, each in its own code block. If it held the commit
   guard back, say that one more `/lanes:init` after that commit installs it. Then
   suggest `/lanes:doctor` to confirm the result. Do not edit the config or commit
   yourself unless the user asks; the files are theirs.
