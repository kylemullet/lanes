# Lanes extension point: preflight

Runs inside `session-startup`, right after the pull and before the queue is read.
Put the steps that are true only of THIS project here — dependency bootstraps, data
mirrors to sync, a local server to start, a scheduled check to offer. The protocol
skill stays generic; this file is where the local facts live.

A step that reports into the Brief gives each result as a status line:

```
<LEVEL> <name>: <detail>          LEVEL is OK, CUE or CRITICAL; the name has no colon
```

`OK` means nothing to read. `CUE` is worth a glance and is never a finding. `CRITICAL` also
goes on the `critical:` line, whatever mode the operator picks. The startup sequence folds
every `OK` line into one `health:` line and shows the rest, worst first. A line in any other
spelling is shown in full.

Nothing yet. Delete this paragraph when you add a step.
