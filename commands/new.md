---
description: Mint a backlog issue you are raising — next free ID, reported by you, Context written from what you said
argument-hint: "<PROJECT> \"<title>\" [--type=…] [--priority=…] [--assignee=…] [--epic=ID] — or just describe it"
allowed-tools: 'Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_new.py:*), Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" push_guard.py:*), Read, Edit'
---

Create a backlog issue the user is raising, then fill it in.

1. Turn the arguments into the script's form: a project prefix, a quoted title, and any
   options. When the user wrote the form already, pass it through unchanged. When they
   described the issue in prose, choose the project from the configured prefixes, write
   a short title, and say which you chose. If no project fits, ask instead of guessing.
   The arguments were: $ARGUMENTS

2. Run it from the repository the session is in, with `--reported-by=me` added unless
   the user named a reporter:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_new.py <PROJECT> "<title>" [options] --reported-by=me
   ```

   `me` resolves to this machine's operator. A slash command is the operator typing, so
   the issue is theirs; an issue a session raises on its own calls the script directly
   with `--reported-by=claude`, and that split is the point. If the script refuses `me`
   (a machine with no operator row), relay the refusal and ask who is reporting it.

3. Read the file the script printed (`created <path>`) and replace the Context stub with
   what the user said: the problem, where it shows, and any fix they suggested, in their
   terms. Leave Current status and Resolution as written. Do not change the frontmatter.

4. Publish it, so the other machines see it now rather than at the next OK'd push. From
   the main clone on the main branch, commit that one file and push it under the OK-free
   guard (a backlog-only push needs no OK, LANES-5):

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" push_guard.py --ok-free --push --add <path> -m "docs(backlog): open <ID> — <title>"
   ```

   Inside a lane worktree, skip this: the issue rides in the lane's own commit. If the
   guard refuses (other work on local main), the issue is committed and stays local;
   relay the reason.

5. Tell the user the new ID, its title and its path, and whether it was pushed.
