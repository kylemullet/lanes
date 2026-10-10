# Session startup — the incidents behind the rules

Every counterintuitive rule in `SKILL.md` was paid for. Operators are named by role; the
mechanics are kept as they happened. Dates are the day the rule changed.

## The slice claimed by hand (2026-10-06, 2026-10-07)

A directive named four issues. The claim commit covered one; the second was reserved 35
minutes later, after the operator noticed only one showed in progress. Another named ID
had no file on the main branch at all — it existed only on a branch nobody had absorbed —
and the session swapped in a different issue mid-claim without saying so. The next day a
session hand-wrote `**RESERVED, NOT STARTED — queued behind <ID>.**`, copying this skill's
own example, and the doctor's marker regex (which needs the bold to close after the kind)
never recognized it. Writing N markers by hand is a cost enforced only by discipline, so
the claim is now one script: every ID or none, every marker from one spelling, a missing
ID named with where it lives.

## The stale artifact on the branch (2026-09-09)

A startup brief reported an old branch as an undecided merge awaiting the operator, on
the authority of the branch's OWN session asset ("NOT merged — pending his decision",
accurate the day it was written three weeks earlier). The main branch had dispositioned
that branch twice since — parked, then re-confirmed as a permanent reference
implementation, with half of its scope closed as superseded in a later issue. The same
brief reported a finding from that asset as untracked when an issue had closed it the
same day it was found. Both errors were one mistake: trusting a stale artifact *on the
branch* over the live queue on the main branch, which is exactly backwards. Rule: grep
the backlog for a branch before reporting what it waits on; never read a branch's asset
as current state.

## 113 seconds (2026-09-16)

A lane's claim hit the main branch at 23:27:45 saying `ACTIVE LANE, worktree <name>`.
`git worktree add` did not run until 23:29:38. A second session opened inside that
window, found an ACTIVE marker naming a worktree that did not exist and no branch, and
concluded the lane was abandoned. It announced that it would park the other lane's issue
back to `open` inside its OWN claim commit, with an opt-out attached — a takeover wearing
a courtesy note. The operator stopped it by hand. Two rules came out of it: a claim
younger than ~15 minutes is never a stale candidate, whatever the evidence says; and the
marker written before the worktree exists says `WORKTREE PENDING`, not `ACTIVE LANE`.
Claim-first stays — it is the collision primitive, and reordering only trades this race
for a worse one where two sessions pick the same issue in the gap.

The same day, the marker timestamp rule was born: a claim stamped with a UTC date read as
"tomorrow" against its commit's local time, so the claim was dated in the future before
anyone tried to age it. Timestamps are LOCAL and carry minutes.

## Our own claims in block V (2026-09-16)

A brief put a lane that was verified on its branch and awaiting the landing OK, and the
lane reserved behind it, in block V as *the recommended slice* — while both were
`in-progress` from the previous session's claim commit. The exclusion-set rule was
already in the skill; it was skipped because the lanes were the operator's own. A claim
does not care whose it is — that is the whole point of a claim.

## The day with no product work (2026-09-10)

The operator launched several sessions at once on one machine. Some skipped the startup
pull; some worked directly in the main checkout instead of making worktrees. A docs
commit for one issue was made while an unrelated lane's branch was checked out in the
shared clone; the rebase that correctly landed that lane dropped it, so the main branch
advertised a false claim all day. Rescuing that commit spawned two duplicate branches of
the same content. Another lane on a second machine never pulled and re-implemented a fix
that had already landed. ~24 files of finished work sat uncommitted in a worktree nobody
had pushed, one `rm -rf` from gone. None of these were hard problems; they were all the
same problem — two lanes sharing one checked-out HEAD, and a session that started from a
stale tree. Untangling them took a full session that produced no product work. Rules:
anything that is not a claim is worked in a worktree; one issue at a time; pull before
each; never a second front while one is unresolved.

## A stopped session is not a dead session (2026-09-16)

The operator stopped two sessions. A third found their orphaned test suites still
running and killed them. A task ending — including by `kill` — counts as that task
*completing*, which re-invokes the session that owns it; both stopped sessions woke and
had to be stopped again. Never kill another session's background process; let an
orphaned suite finish, or have the operator close its thread.

## The claim that never left the machine (2026-09-14 → 2026-09-16)

For two days the rule was "commit the claim locally, push only when the other operator
is active or a second machine might take the issue". That made a claim's visibility
depend on a guess about who else was working. A local-only claim protected concurrent
sessions on one machine and was invisible to the other operator and any second machine.
Reversed: the claim is committed AND pushed on the directive that starts the work; the
directive is the OK, and the main-direct path guard is the safety.

## The full table that oscillated (2026-09-01 → 2026-09-02)

The brief's full-backlog table was made mandatory because it kept silently not appearing
and the operator was doing the extra step by hand. The sortable HTML view shipped the
same day and superseded it; the next day the operator asked to drop the table in favour
of the link. The link is the report's second section, `Sortable backlog`, so it is not re-litigated
a third time.

## Why the views are generated and gitignored (2026-09-01)

The committed index was the one file every concurrent lane rewrote, so any two live
worktrees conflicted on it at rebase time, and a lane that regenerated it from an
incomplete set of issue files silently deleted the other lane's rows. Untracking it
removed the reason it could happen. Later (2026-09-16) the view started being SERVED and
re-parsed per request, because something still had to remember to run the generator
after every claim and something did not: a claim reached the main branch while the
operator's local views showed the pre-claim state.

## Why the backfill runs at startup (2026-09-02)

A worktree lane cannot know its resolving commit's hash — the close rides in that commit
and the pre-push rebase rewrites it. A lane that cited the hash anyway shipped an orphan
that still resolved locally through the reflog and had never existed on the other
operator's clone. So lanes cite the commit SUBJECT, mark the issue `verified`, and the
certifying machine's next startup — after its pull — fills the hash and closes. One
writer; the two-clone race on the same issue files is what the certifying gate prevents.
