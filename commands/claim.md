---
description: Claim a lane of backlog issues in one pushed commit — every ID or none; the first WORKTREE PENDING, the rest RESERVED behind it
argument-hint: "<ID> [<ID> …] [--name \"lane name\"] [--files \"a, b\"] [--behind <ID> | --next-in <ID>] [--dry-run]"
allowed-tools: 'Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_claim.py:*), Read'
---

Claim the named backlog issues for this session, in the order given. `--behind <ID>` adds
them to the end of a lane already claimed; `--next-in <ID>` puts them at its front, as the
next to work, and moves an issue this machine claimed alone in a lane of its own.

1. A new lane needs a name (LANES-80): the arguments start one unless they carry `--behind`
   or `--next-in`. When they start one and carry no `--name`, add `--name "<a few words>"`
   on what the lane is about, drawn from what the operator said or the issues' titles, and
   say which name you chose. The arguments are otherwise passed through as written.

2. Run, from the repository's main clone on its main branch:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_claim.py $ARGUMENTS
   ```

3. Relay the result. On exit 0 list each ID with its marker kind, the lane's name and the
   commit subject. On exit 1 nothing was written: quote the `NOT CLAIMED` line, and if it
   names an ID that lives only on another branch, say so plainly — whether to re-scope is
   the operator's decision. On exit 2 the claim is committed locally but not pushed; quote
   the reason. Never edit an issue file to get around a refusal.
