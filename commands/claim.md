---
description: Claim a slice of backlog issues in one pushed commit — every ID or none; the first WORKTREE PENDING, the rest RESERVED behind it
argument-hint: "<ID> [<ID> …] [--files \"a, b\"] [--behind <ID>] [--dry-run]"
allowed-tools: 'Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_claim.py:*), Read'
---

Claim the named backlog issues for this session, in the order given.

1. Run, exactly, from the repository's main clone on its main branch:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_claim.py $ARGUMENTS
   ```

2. Relay the result. On exit 0 list each ID with its marker kind and the commit subject.
   On exit 1 nothing was written: quote the `NOT CLAIMED` line, and if it names an ID
   that lives only on another branch, say so plainly — whether to re-scope is the
   operator's decision. On exit 2 the claim is committed locally but not pushed; quote
   the reason. Never edit an issue file to get around a refusal.
