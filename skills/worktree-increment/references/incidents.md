# Worktree increment — the incidents behind the rules

Operators are named by role; mechanics as they happened; dates are when the rule changed.

## 113 seconds (2026-09-16)

A lane wrote `ACTIVE LANE, worktree <name>` at 23:27:45 and did not run `git worktree
add` until 23:29:38. A second session opened in between, found an ACTIVE marker naming a
worktree that did not exist, and concluded the lane was abandoned. `WORKTREE PENDING` is
the fail-safe reading of that window, and the empty topic branch is pushed at creation so
an ACTIVE claim is verifiable from any machine — `git worktree list` is local-only.

## The takeover with an opt-out (2026-09-16)

Both the startup and increment skills already said to surface a suspected stale claim *as
a question, never a takeover*. A session satisfied that wording while doing the thing it
forbids: it announced it would park the other lane's issue back to `open` as part of ITS
OWN claim commit, "say the word if you'd rather finish it first." The operator stopped it
by hand. Had it run, a live lane's claim would have been reverted and the revert folded
into an unrelated issue's commit. An intention can be complied with while being
violated; a prohibition cannot — so the rule is now absolute: never write to another
issue's claim.

## One checkout, two lanes (2026-09-10)

A docs commit for one issue was made in the main clone while another lane's branch was
checked out there. The rebase that correctly landed that lane dropped the commit, and the
main branch advertised a false claim for a day; two duplicate rescue branches
accumulated trying to recover it. The position check (step 0) and, later, the hook that
enforces it both come from this. Note the hook refuses on EITHER condition — the write
that caused this had HEAD on a topic branch, so an "AND" form would have passed it.

## Claim the whole slice (2026-09-13)

The operator was about to open a second agent session mid-slice and found issues 3 and 4
of the slice unclaimed — the exact collision the mechanism exists to prevent. Claims are
made for the whole slice up front; work proceeds one issue at a time.

## The hash that resolved locally (2026-09-01)

A lane cited its resolving commit's hash in the issue, the Resolution and the session
asset. The pre-push rebase rewrote the commit. The old hash still resolved on the lane's
machine (reflog) — `git cat-file -e` passed, `git log --oneline <hash>` printed the right
subject — and had never existed on the other operator's clone. Caught by hand. Since
then: cite the commit SUBJECT in backticks; `commit:` stays null until the certifying
machine's startup backfills it; `--check` fails any hash that is not an ancestor of HEAD.

## The suite that never ran the corpus (2026-09-13)

A lane skipped its data-mirror setup; the suite reported a clean pass and exit 0, and the
167 missing tests were visible only as 5 extra skips against the baseline's 20. The lane
was minutes from landing on a green that had never run the fixture corpus. Hence: compare
COLLECTED counts against the baseline, reconcile to test IDs, and treat a shortfall as a
short environment, never as "the code is fine".

## The suite that slept (2026-09-14)

Three unattended full-suite runs "hung" on a laptop — one at 3% for half an hour at 99%
CPU; two 84-second test files took 36 minutes each. The machine dozed between tool calls
and the test runner's clock excludes sleep. The tell is a short reported duration against
a long elapsed time. Keep the machine awake for an unattended run; a closed lid on battery
defeats that too and needs the operator.

## Rebase first, verify once (2026-09-16)

The original order was verify → hold → rebase → re-verify, and re-establishing a full
green on every move of the main branch cost a lane up to three runs of ~430 seconds, when
41 of 59 recent landings had touched nothing a test could see. Now the lane rebases
before the self-verify, and a post-rebase re-run is scoped to what the incoming commits
can reach (`tests.rebase_rerun_command`) with the full suite as the fallback whenever a
path is global or unmapped.

## The variable that was one argument (2026-09-26)

`ARGS=$(classifier --argv-only); pytest $ARGS` handed the test runner ONE argument in
zsh, which does not word-split an unquoted variable, and it died with "unrecognized
arguments" — reading as if the classifier had printed garbage. Inline `$(...)` splits in
both shells; a lane lost a re-run cycle learning that.

## Six lanes without the line (2026-09-02 → 2026-09-16)

The doc-loop step said "skip when no code changed" and named five code directories, so
the infra class skipped by rule: a CI change left the standing docs describing a retired
CI shape for two days; skill-only lanes changed the process while the docs kept
describing the old one. Six code lanes shipped without a `Docs:` line in two weeks,
because the only check was a closeout step that worktree sessions never run. Now
everything outside the docs lane runs the loop, the outcome is recorded in the Resolution,
and `--check` enforces it at the push gate.

## The batching convention broken five times (2026-09-13 → 2026-09-14)

Each landing cost a ~53-minute CI run, so landings were told to batch to one a day. The
convention was broken five times in its first three hours and the day still billed ~700
minutes. The fix removed the cost instead of asking for discipline: CI no longer runs on
push, a landing costs a seconds-long backlog gate, and lanes land as they are verified.
A cost that is only enforced by discipline is not enforced.

## The stale tab (2026-08-25, 2026-08-26)

An operator reviewed an example against a server booted before the fix it was meant to
show, and the next day reviewed a view against a tab holding the old JS bundle — new
backend, old bundle — which reads exactly like the fix not working. Restarting and
rebuilding is the lane's job; "reload the tab" goes in the handoff; and with two lanes up,
a shared port compares the wrong server's bundle to this lane's disk and passes.

## The clean-up that ran after a failed landing (2026-10-07)

A session landed and cleaned up in one shell line — fetch, the fast-forward check, the
landing push, then `;`, then `git worktree remove`, `git branch -D` and
`git push origin --delete`. Another session had pushed a backlog commit to the main
branch seconds earlier, so the fast-forward check failed and nothing landed. The `;`
ran the clean-up anyway: the worktree was removed and the branch deleted locally and on
origin. The commit survived only as an unreachable object; `git fsck --unreachable
--no-reflogs` and a subject grep found it, and it was restored, rebased and landed.

The session broke step 5's own warning about exit statuses, but the skill had a gap
too: step 10 let the worktree go once the branch was *pushed*, and never said when the
*branch* could go, so a tidy session deleted it with the worktree. With concurrent
sessions a lost fast-forward is routine. The fix is mechanical, because the prose rule
had just been broken: `lanes_land.py` gates every clean-up step on a landing it reads
back from the remote, and the branch is deleted only once it has landed.

## Six verified issues and a question (2026-10-07)

A session landed two lanes, then ended by asking the operator whether to run the backfill
for six verified issues. The backfill needed no OK, and nothing in the protocol would
run it before the next startup, a whole session later. It lived at startup because a
lane cannot know its resolving hash: the pre-push rebase rewrites it. That reason ends
the moment the landing reads back from the remote. So the landing closes its own issue,
closeout sweeps what is left, and startup is the backstop. Housekeeping the protocol has
already authorized is run and reported, never put to the operator as a question.

## The `cd &&` that was refused (2026-09-01)

A permission allow-rule for `git *` is a PREFIX match over the command string, so `cd
<worktree> && git push …` matched nothing and was refused — for a push that was fully
authorized. `git -C <worktree> push …` ran. Handing the operator a command to paste was
the most avoidable friction in the flow.
