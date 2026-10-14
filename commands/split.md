---
description: Split an issue bigger than one landing into an epic and its children — one command, one backlog-only push
argument-hint: "<ID> \"<child title>\" [\"<child title>\" …] [--type=…] — or describe the pieces"
allowed-tools: 'Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_split.py:*), Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" push_guard.py:*), Read, Edit'
---

Split the named issue into an epic with one child per piece of work, so each piece can be
claimed, prioritized and dated on its own (LANES-47). An issue worked in phases never
closes; this is the alternative.

1. Turn the arguments into the script's form: the issue ID, then one quoted title per
   child, in working order. When the user described the pieces in prose, read the issue
   file, write a short title for each, and say what you chose. The arguments were:
   $ARGUMENTS

2. From the main clone on the main branch, run it with `--reported-by=me` added unless the
   user named a reporter, first with `--dry-run` to show the IDs, then for real with
   `--push`:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" backlog_split.py <ID> "<child>" ["<child>" …] --reported-by=me --push
   ```

   An open, blocked or paused issue becomes the epic and the children go under it; an
   epic only gains children. A claimed issue is the partial-landing case: run it from the
   lane's worktree WITHOUT `--push`, and the files ride in the lane's commit
   (`worktree-increment` step 9.1). A verified or closed issue, or another session's claim,
   is refused: quote the `NOT SPLIT` line and stop.

3. Fill in each child's Context: read the parent's Context and write into each child the
   part it carries, in the parent's terms. Leave Current status and Resolution as written,
   and do not change the frontmatter. Then publish the edits under the OK-free guard:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" push_guard.py --ok-free --push --add <child paths> -m "docs(backlog): <ID> children — Context"
   ```

4. Report the epic, each child's ID and title, and the push result. An epic is never
   claimed: a slice that named the split issue claims its children instead.
