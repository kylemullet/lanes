---
description: Mint a backlog issue you are raising — next free ID, reported by you, Context written from what you said
argument-hint: "<PROJECT> \"<title>\" [--type=…] [--priority=…] [--assignee=…] [--epic=ID] [--due=YYYY-MM-DD] — or just describe it"
allowed-tools: 'Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_new.py:*), Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" push_guard.py:*), Read, Edit'
---

Create a backlog issue the user is raising, then fill it in.

1. Turn the arguments into the script's form: a project prefix, a quoted title, and any
   options. When the user wrote the form already, pass it through unchanged. When they
   described the issue in prose, choose the project from the configured prefixes, write
   a short title, and say which you chose. If no project fits, ask instead of guessing.
   When they named a firm date — a deadline, a dated event, the day it stops being
   movable — pass it as `--due=YYYY-MM-DD`; a date they would merely like to hit is
   priority, not a due date. The arguments were: $ARGUMENTS

2. Run it from the repository the session is in, with `--reported-by=me` added unless the
   user named a reporter, and `--push`, so the ID is reserved on origin the moment it exists.
   From a lane worktree `--push` mints into the main clone and pushes from there (LANES-63: an
   issue minted in a worktree takes a number another lane can land first). When the user's
   words give the Context, pass it as `--context "<their problem, where it shows, the fix they
   suggested>"`, so that one push carries the whole issue:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_new.py <PROJECT> "<title>" [options] --reported-by=me [--context "…"] --push
   ```

   `me` resolves to this machine's operator. A slash command is the operator typing, so
   the issue is theirs; an issue a session raises on its own calls the script directly
   with `--reported-by=claude`, and that split is the point. If the script refuses `me`
   (a machine with no operator row), relay the refusal and ask who is reporting it.

3. Read the file the script printed (`created <path>`, in the main clone) and, unless
   `--context` carried it, replace the Context stub with what the user said: the problem,
   where it shows, and any fix they suggested, in their terms. When they said what done looks
   like, write it into the Acceptance criteria table
   as concise test cases, one per row (AC1, AC2, …): Owner is who will verify it, and Test ID
   names an automated test only when one already exists. If they said nothing about done,
   leave the table's stub for the lane to fill. Leave Current status and Resolution as
   written. Do not change the frontmatter.

4. When step 3 changed the file, publish the edit the same way the mint went: from the main
   clone on the main branch, commit that one file and push it under the OK-free guard (a
   backlog-only push needs no OK, LANES-5):

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" push_guard.py --ok-free --push --add <path> -m "docs(backlog): <ID> — context"
   ```

   A lane session does this from the main clone too — never "it rides in the lane's commit"
   (LANES-63). If the guard refuses (other work on local main), the commit stays local; relay
   the reason.

5. Tell the user the new ID, its title and its path, and whether it was pushed.
