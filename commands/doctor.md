---
description: Check the lanes setup — config valid, installed vs expected plugin version, extension-point files, backlog integrity, stale-claim candidates
argument-hint: "[--strict] [--json]"
allowed-tools: 'Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_doctor.py:*), Read'
---

Diagnose the `lanes` setup for the repository the session is in.

1. Run, exactly:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" lanes_doctor.py $ARGUMENTS
   ```

   Every line is `OK`, `WARN`, `FAIL` or `SKIP` with a label and a detail. Exit status
   1 means at least one `FAIL` (or, with `--strict`, at least one `WARN`).

2. Relay the result to the user as the lines came out, grouped: failures first, then
   warnings, then one line saying how many checks passed. Keep the wording of each
   detail; it was written to be read.

3. For each `FAIL` or `WARN`, say what fixes it when the script said so (it names
   `/lanes:init` for a missing config or stub, the two versions on drift, and the
   `release_tag.py --ensure --push` line for a pin with no release tag).

4. **Stale-claim candidates are questions, never actions.** If the doctor lists an
   `in-progress` issue as a stale-claim candidate, report it and ask the user. Do not
   edit that issue's status, marker or timestamp: a claim belongs to the session that
   made it, and only that session or the operator releases it. A claim younger than the
   15-minute floor is never a candidate, whatever else the evidence says; the script
   already applies that rule.
