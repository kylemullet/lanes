# Session closeout — the incidents behind the rules

Operators are named by role; mechanics as they happened; dates are when the rule changed.

## ~24 files, one `rm -rf` from gone (2026-09-10)

A session ended with ~24 files of finished work — a CI matrix and a console-encoding
sweep, both complete — sitting uncommitted in a worktree that had never been pushed.
Nothing in the closeout looked there, because it ran in the main clone and `git status`
was clean. It survived only because a later session went looking for something else.
Committed-and-pushed is the *minimum* resting state for work that exists; "still in
progress" is not a reason to leave it on one disk. Step 1b sweeps every worktree.

## A stopped session is not a dead session (2026-09-16)

The operator stopped two sessions; a third killed their orphaned test suites at closeout;
both stopped sessions woke — a task ending, including by `kill`, re-invokes the session
that owns it — and had to be stopped again. Never kill another session's background
process; let it finish, or have the operator close its thread.

## The asset the author could not read (2026-05-28 → 29)

A second operator worked a session without access to their own prior session asset,
because it had been written on a sync-mirrored path and never committed. Since then: any
untracked project text is committed before the closeout push, whoever wrote it and
whether or not this session processed it.

## The pathspec that matched nothing (2026-06-13)

`git status -- 'dir/**'` silently matched nothing and reported a false "(none)" over a
real untracked asset. The detection command is `git status --porcelain
--untracked-files=all | grep '^??'`, unfiltered, and then eyes.

## The ledger that was gitignored (2026-08-25)

A plain Markdown ledger named in the standing docs as *the* record of four rounds of
ratified conventions sat under a directory-level ignore rule. It opened, diffed and
edited normally in every local view while `git status` stayed silent, so none of it had
ever reached the main branch and the other operator could not read any of it. Before
treating a file as a shared record, `git check-ignore -v <path>`; if it is ignored and
carries decisions, the file itself moves to a tracked home.

## The hash that resolved locally (2026-09-01)

A rebase before push rewrote a cited commit hash; the orphan still resolved on the
author's machine through the reflog and had never existed anywhere else. Re-run the
backlog check AFTER the rebase, every time; cite subjects, not hashes, until a commit is
on the main branch.

## The pipeline that hid a conflict (2026-09-01)

`git pull --rebase … 2>&1 | tail -5 && <next>` reported `tail`'s exit status; a rebase
that stopped on a conflict read as success and the chain ran on — in a worktree lane, all
the way to `git reset --mixed HEAD~1` inside the conflicted rebase. Load-bearing status
checks get their own line, a log file and an echoed `$?`. A check that cannot fail is
worse than none.

## The reserved claims nobody released (2026-09-13)

A slice claims every issue up front, so a session that ran out of time left
`status: in-progress` on issues with no worktree and nobody behind them — stale claims
that were easier to create than abandoned active ones because nobody had touched the
files. Closeout releases THIS session's unreached reservations; another session's claims
are surfaced and left alone.

## Verify-first that went false (2026-05-22)

A primitive was promoted to "done" on green inference tests with zero outputs produced,
and the state stayed false for nine days. The lesson generalizes: auto-tests green is not
the operator's eyes on the output. A project with an output gate runs it from
`pre-land.md`; the protocol itself only insists that the gate, if one exists, is run
before the promotion is written down.

## The batching convention broken five times (2026-09-13 → 2026-09-14)

Landings were told to batch to one a day because each cost a ~53-minute CI run; the rule
was broken five times in its first three hours and the day billed ~700 minutes anyway.
The cost was removed instead: CI no longer runs on push, lanes land as they are verified,
and closeout lands only the remainder — enumerated by lane, so the OK is informed consent.

## The sweep that took another lane's server (2026-09-16)

A closeout that tidied the whole local-port band would have killed a worktree lane's
server mid-verification on another session. Port sweeps are scoped to what the checkout
owns.
