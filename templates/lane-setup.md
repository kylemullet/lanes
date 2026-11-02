# Lanes extension point: lane setup

Runs inside `worktree-increment`, right after `git worktree add` returns and before
the first edit. Put the per-worktree setup that is true only of THIS project here —
fixtures to copy in, a virtualenv or `node_modules` to link, a port to resolve.

A project that runs a local server and is previewed through a harness tool that reads a
launch file from the main clone (the desktop app's `.claude/launch.json`) says here how a
lane adds and removes its own entry: every lane on the machine shares that file
(`worktree-increment` step 6.3, LANES-72).

Nothing yet. Delete this paragraph when you add a step.
