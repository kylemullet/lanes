# Changelog

## 0.4.62 — the startup shows the Brief before it asks what to work on (2026-10-29)

- **The operator never saw the Brief** (LANES-70). Kyle: *"its running the questionnaire before
  the brief. The brief isn't particularly useful if you get it after youre asked what you want
  to work on."* Since 0.4.59 a script renders the Brief, and its output is a tool result the
  harness folds out of sight. The session ran it, took that as having shown the Brief, and
  asked the mode and project questions with neither the Brief nor the view link in front of the
  operator. That happened in all three startups since 0.4.59; all seven before it showed the Brief.
  It also undermined 0.4.60's diff Brief, which compared each startup against a Brief nobody had read.
- **`lanes_brief.py` prints the reply itself:** `**Brief**`, the Brief in a code block, then
  `**Sortable backlog**` and the view's link (the main clone's `file://` view, or the served
  URL), ready to paste. One stderr line tells the session the operator has not seen it.
- **The startup skill says so in step 7's own heading**, "running the script shows the operator
  nothing", and step 8 asks the question after the pasted Brief in the same message, never in
  its place. The incident is "The Brief behind the question".

## 0.4.61 — the mark is mirrored, tall lane on the left, so it reads as an L (2026-10-28)

- **The mark is flipped left to right** (LANES-69). Kyle: *"it looks more like an L this way"*.
  The tall lane is now on the left, landing high on the main line, and the short lane on the
  right, landing low. The strong stagger (0.4.55) is unchanged: the same landing heights,
  stroke and colours, mirrored about the main line.
- **Everywhere the mark lives:** the vector source and the alternate beside it, so the
  alternate stays a swap; the copy embedded in `backlog_index.py` that draws the backlog view's
  header and tab icon; and the 1024px listing PNG. The PNG's strokes are mirrored in place, and
  every pixel outside them is unchanged, so it keeps its square, corners and format (RGB, white
  corners). No text names either file by path (0.4.7).

## 0.4.60 — after the first Brief, a startup reports only what changed since the last one (2026-10-28)

- **Every startup re-reported the same news** (LANES-68, the last piece of the LANES-65 epic).
  With four or five sessions open at once, each startup repeated the same landings, the same
  canary run and the same lanes; "since last session" meant nothing.
- **`lanes_brief.py` saves what it reported** in the clone's git directory
  (`.git/lanes/last-brief.json`): per machine, shared by every worktree and session of the clone,
  never tracked. The next run, from any session on the machine, renders only what changed:
  - a `since <HH:MM>:` line with what landed (since the tip the last Brief read), the issues
    opened and closed, and the lanes started and ended, or `nothing changed`;
  - a `CUE` whose level has not moved folds into `health:` as unchanged, and a check whose level
    moved shows once, an `OK` one marked `(was <LEVEL>)`;
  - `lanes:` reads `N in flight, unchanged`, and `branches:` is left out, while their sets match.
  - `critical:`, `due:`, the session's notes and the stat are always in full.
- **`--full`** renders the whole Brief whatever was saved; **`--no-save`** leaves the saved Brief
  alone. With no saved Brief, or an unreadable one, the whole Brief renders, as in 0.4.59.
- Tests pin a repeat Brief that says nothing changed, the `since` line's kinds, a moved check,
  another day's label, where the state lives (in the git directory, shared by a worktree, never in
  `git status`), `--full` and `--no-save`, and step 7's wording.

## 0.4.59 — a script renders the Brief: critical first, lanes on one line, a title on every ID (2026-10-28)

- **The session wrote the Brief from prose at every startup** (LANES-67, the LANES-65 epic). It
  drifted between sessions, put the `critical:` line last, cited bare IDs ("New issues today:
  DOC-115, INFRA-139, …"), gave each in-flight lane a line or more, and reported a reference
  branch that will never land at every startup.
- **`lanes_brief.py` renders it**, in one fixed order, leaving out a line with nothing to say:
  `critical:` (always), the `CUE` and unmarked status lines, `due:` (overdue or within seven
  days), `lanes:` (every lane in flight on one line), the session's notes, `branches:`,
  `landed:` (issues cited by commits since the pull), `health:`, and the backlog stat (always).
  It folds the status lines on stdin through `status_lines.py`, cuts every cited title to its
  first clause, and prints the same text for the same state.
- **The session's judgment goes in as arguments, and only there**: `--critical` for what is
  urgent and no check reports (a stale claim, a landing to OK), `--note` for what the lanes need
  (two lanes expecting one file, a branch's disposition, a staleness mark). The critical line no
  longer takes the priority field: an issue is not urgent by having the top priority.
- **`git.permanent_branches`** (fnmatch patterns, default `[]`) names branches meant never to
  land, which the Brief never lists as unlanded.
- Step 7 of `session-startup` runs the script and shows its output as printed; step 2 names the
  new key. Tests pin the order, the critical line's sources, titles, the lane line, the
  determinism, the branch filter, the landed range, the CLI and the config key; each fails
  without the change.

## 0.4.58 — every startup check reports OK, CUE or CRITICAL, and the OK ones fold into one health line (2026-10-27)

- **Most of the Brief said nothing changed** (LANES-66, the first piece of the LANES-65 epic). On
  one project's Brief, 7 of 14 bullets were all-clear checks, each in its own words, and the one
  line that had to be read was last. Kyle: *"The brief isn't really working for me."*
- **A status-line contract.** Every check that reports into the Brief, the protocol's own and
  every `preflight.md` step, gives each result as `<LEVEL> <name>: <detail>`, with LEVEL `OK`,
  `CUE` or `CRITICAL`. `OK` means nothing to read; `CUE` is worth a glance and never a finding;
  `CRITICAL` also goes on the `critical:` line. Step 7, the `preflight.md` template and the
  README say it in the same words.
- **`status_lines.py` folds them.** It prints the `CRITICAL` lines, then the `CUE` lines, then any
  line in another spelling, and last one `health:` line naming every `OK` check (`health: all
  clear — pull · doctor · …`). A line in another spelling is shown in full, so an unmarked check
  is never folded out of sight.
- **The protocol's own checks are levelled from a table in step 7** (pull, doctor, commit guard,
  view hooks, backfill, backlog check). They keep printing in their own words for now; the Brief
  script (LANES-67) reads them directly. Step zero's "needs no Brief line" rules became their
  `OK` level.
- Tests pin the parse, the fold's order, the health line, unmarked lines shown in full, the CLI,
  and the contract's wording in all three places. Each fails with the change reverted.

## 0.4.57 — the startup sequence asks which project beside the mode (2026-10-27)

- **The mode question had no room for a project** (LANES-64). An operator's sessions were
  already one project each in practice, but the menu took a project only when it was typed into
  "Other", so nobody saw the option. Kyle: *"a second question after the type of work where it
  asks if we want to work on a specific project from the backlog"*.
- **Step 8 asks the mode and the project in one dialog.** The question tool takes several
  questions at once, so the project costs a choice, not a round trip. The project question offers
  "Any project", then the top three rows of the report's new `PROJECTS` block, and allows more
  than one answer; "Other" takes prefixes, an epic ID or a theme.
- **Triggers answer either question.** A mode word answers the mode, a project prefix the project
  (`GA deep dive CORE`), and a prefix alone means Deep Dive in that project (`GA ui`), as an issue
  ID already did. Critical never asks the project, and ignores it when both are asked together.
  A config with one project never asks it.
- **The project narrows the proposals, never the Brief.** It filters the eligible set in every
  mode but Critical, and the `critical:` line above the question is untouched by it.
- **`backlog_index.py --report` ranks the projects** in a `PROJECTS` block between Due and the
  backlog: those with an issue opened, claimed or closed in the last three days first, then the
  most open, and a project with nothing open last. Each row gives its open count, how many of
  those are high or critical, and its recent activity. The ranking is computed, so every session
  offers the same three.
- Tests pin the ranking, the activity window, the configured prefixes, the block's place in the
  report and the skill's wording. Each fails with the change reverted.

## 0.4.56 — every issue carries an acceptance-criteria table: AC, test case, owner, test ID (2026-10-26)

- **An issue had nowhere to say what done looks like** (LANES-60). A minted issue got Context,
  Current status and Resolution. Acceptance, where it was stated at all, was a line of prose in
  Context, and the tests that proved an issue were named only after the fact, in the Resolution's
  evidence. Kyle: *"adding acceptance criteria to jiras. Concise test cases with test id's when
  there's automation"*.
- **`backlog_new.py` and `backlog_split.py` now mint a fourth section, `## Acceptance criteria`,**
  between Context and Current status: a table of `AC | Test case description | Owner | Test ID`,
  one concise test case per row. Owner is who verifies it. Test ID names the automated test that
  proves it, and stays blank for a manual case. The claim still writes its marker under Current
  status and leaves the table alone. Issues minted earlier keep their three sections; `--check`
  does not require the table.
- **`/lanes:new` writes the rows** when the operator says what done looks like, and otherwise
  leaves the stub for the lane.
- **The lane works from the table** (`worktree-increment`). It writes the rows before building
  when they are still the stub, or when the issue predates the section. It puts each automated
  test's ID in its row as the test is written. The hold's debrief reports every row: an automated
  row's Test ID and that it passed, and which verification step covers a manual row. At landing,
  every row carries its Test ID, or a blank one whose Owner checked it.
- Tests pin the section's place and header in a minted issue and in a split child, that a claim
  leaves it untouched, and that the command and the skill say how to fill it. Each fails with the
  change reverted.

## 0.4.55 — the mark is the strong stagger, which still reads as staggered at 16px (2026-10-26)

- **The 0.4.51 mark lost its stagger at small sizes** (LANES-59). Its side lanes land on the main
  line only a little apart, and at 16px, the tab icon's size, they read as landing at one height,
  a symmetric fork. Kyle: *"the staggering is barely visible at smaller resolutions"*.
- **The stronger-stagger variant kept beside it since 0.4.51 is now the mark everywhere:** the
  vector source, the 1024px listing PNG, and the copy embedded in `backlog_index.py` that draws the
  backlog view's header and tab icon. The left lane lands lower and the right one higher, and both
  still read as separate heights at 16 and 24px. The previous mark is kept as the alternate vector
  source, so the choice stays a swap. The listing PNG keeps the old one's square, corners and
  format (RGB, white corners); only the strokes inside it are re-rendered. No text names either
  file by path (0.4.7).

## 0.4.54 — a slice is a lane; startup and closeout read as the startup and shutdown sequences (2026-10-25)

- **One word for a claimed group of issues: a lane** (LANES-57). Since LANES-49 a slice was already
  recorded as its lane (the `lane:` line, the lane cards, `--next-in`), so the protocol had two
  words for one thing. Kyle: *"claim a lane instead of a slice"*. "Slice" is gone from the skills,
  their incident files, the commands, the README, the templates, and the scripts' help and
  messages. The claim script's RESERVED marker now reads "Claimed as part of the <date> lane". The
  parser keys on "queued behind <ID>", so markers already written with "slice" still parse, and a
  fixture keeps that checked.
- **"Lane" no longer means two things in one passage.** Where the old text used "lane" for one
  issue's worktree next to "slice" for the group, the issue's side now says "worktree" or
  "increment". For example: "Never open a second issue's worktree while the first is unresolved".
  The `ACTIVE LANE` marker and the `lane:` line are unchanged. They are parsed, and "ACTIVE LANE"
  reads as the lane's active issue.
- **The operator reads "startup sequence" and "shutdown sequence"; the identifiers stay.** The
  `session-startup` and `session-closeout` skills are titled *Startup sequence* and *Shutdown
  sequence*. Their descriptions say so, and closeout gained a "shutdown" trigger. "Session startup"
  and "closeout" in prose became the sequences, or "startup" / "shutdown" for short. The skill
  names, every `/lanes:` invocation and every reference to them are unchanged, so no trigger and
  no consumer's docs break.
- **"Land" stays.** A landing is a fast-forward push of a verified branch, never a git merge, and
  calling it one would misdescribe the operator-OK gate.
- `tests/test_skills.py` guards the result. It fails if "slice" reappears anywhere the protocol
  speaks to the operator, except one quoted line that means a scoped test re-run. It also fails if
  the two skills lose their sequence titles or identifiers, or if "session startup" or "closeout"
  returns in prose. CHANGELOG history keeps its words.

## 0.4.53 — the Due section shows five, then "Show N more" (2026-10-25)

- **The Due section pushed everything else down the page** (LANES-56). Since LANES-46 the HTML
  view opens with every dated live or verified issue. Readlines has 17, so the lanes and the queue
  started a screen below the header.
- **The view now shows the first 5, plus every overdue one, however many.** The rest wait behind a
  "Show N more" button, which becomes "Show fewer". The section's count stays the full count, and
  the choice is remembered the way the Filters panel is. The server renders the first paint. The
  page script re-folds after every filter and every sort, counting only the rows the filter leaves,
  in their current order. So a narrow filter shows no button, and re-sorting never puts an overdue
  issue behind it. Folding is a class on the Due table, not the rows' `hidden` attribute, which the
  filter owns. `INDEX.md`, `--report` and the Brief are unchanged.
- Tests cover five or fewer rows (no fold), the fold past five, overdue rows past five, and the
  script hooks. The script was also driven in headless Chrome: fold, unfold, filter, clear, and
  re-sort with the overdue rows at the bottom. No overdue row was ever hidden.

## 0.4.52 — the backlog view's header is the mark, then "Lanes | <repo> Backlog" (2026-10-25)

- **The view's header and tab now say whose page it is** (LANES-54). The header used to read
  `Backlog · <repo>` and the tab `Backlog — <repo>`, with no mark. Now the header is the lanes mark
  (0.4.51), **Lanes**, a faint `|`, and `<repo> Backlog`. The tab title reads the same, and the tab
  icon is the mark. Both copies of the mark are embedded in `backlog_index.py` rather than read
  from the plugin's assets, because no plugin text names the icon files by path (0.4.7). The page
  still fetches nothing. The header's copy is inline SVG, which needs no namespace URL. The tab
  icon is a standalone SVG, which does, so it is a base64 `data:` URI. The self-contained-page test
  now allows exactly that one `<link>`.
- **The view is titled with the main clone's name, whichever checkout refreshes it.** Since LANES-11
  any checkout regenerates the main clone's view from the main clone's files, but the repo name
  stayed the calling checkout's. A refresh from a lane's worktree, or from the landing's throwaway
  close worktree, titled the page with that directory's name. The new header made this hard to
  miss. The redirect now carries the name too, and `test_backlog_new.py` pins it.

## 0.4.51 — a simpler icon: three lanes landing on one line at staggered heights (2026-10-25)

- **The 0.4.6 icon was too busy to read small** (LANES-58). It had a trunk ending in an arrow,
  two lanes that left and rejoined it, a third that ended in a square, and three circles, every
  stroke drawn twice as an outline. That is ten shapes, and at 16 and 24px the circles and inner
  strokes blurred together. Its first use inside the product will be the backlog view's header
  (LANES-54), at about 24px.
- **The new mark is three strokes,** amber on the same dark rounded square: a straight main line,
  with a lane on each side landing on it at different heights, left low and right high. Kyle
  picked it from candidates rendered at 16, 24, 64 and 160px on light and dark backgrounds, where
  it reads at every size. A stronger-stagger variant he also liked is kept beside it as the
  alternate vector source. The 1024px listing PNG is re-rendered from the new source, RGB with
  white corners like the old one. No text names either file by path (0.4.7).

## 0.4.50 — the Privacy section names what `/lanes:init` reads and adds (2026-10-25)

- **0.4.49 left the README's Privacy section incomplete in two places** (LANES-53). The section
  promises everything the plugin reads, and it named only `/lanes:doctor` as reading Claude Code's
  plugin registry. Since 0.4.49, `/lanes:init` reads it too, to find the marketplace lanes came
  from and copy that source into `.claude/settings.json`. Its "Other effects on your disk" did not
  say that init now adds lanes to that file, which decides what Claude Code prompts everyone
  opening the repository to install. LANES-52's doc pass updated only the hooks paragraph.
- **Both are now stated.** "What it reads" names the two commands that read the registry and why,
  and says neither sends what it reads anywhere. "Other effects on your disk" says what init adds
  to `.claude/settings.json`, that it never removes or changes another key, and when it leaves the
  file alone. Checked against the 0.4.49 code: init makes no network call, and nothing else it
  reads or writes is missing from the section. README only; no code changed.

## 0.4.49 — `/lanes:init` sets up everything the doctor checks (2026-10-25)

- **A fresh repo that followed init's own instructions met five doctor warnings** (LANES-52).
  `/lanes:init` wrote the config and the three stubs and nothing else, then said "run
  /lanes:doctor". In a throwaway repo on 0.4.48 the doctor answered: config untracked, *docs/backlog
  does not exist yet*, *.claude/settings.json absent*, no commit guard, no view hooks. After the
  commit and a first issue, four were still there, with the views warning in place of the backlog
  one. No lanes script wrote a `.gitignore` or a `settings.json`, and only `session-startup`
  installed the hooks.
- **Init now sets up all of it.** It creates the backlog folder (`backlog.dir`) with a
  `README.md`, and gitignores the two generated views with a `.gitignore` inside that folder, unless
  they are ignored already. It declares lanes in `.claude/settings.json` from the marketplace this
  machine installed it from, copying the source from `known_marketplaces.json`, which is the record
  the doctor's `marketplace` line compares against. It installs the view hooks and the commit guard.
  `settings.json` is only ever added to: other keys stay, a lanes entry already there is kept byte
  for byte, `"lanes@…": false` is left alone, and a file it cannot parse is reported, not rewritten,
  `--force` included. A machine with no marketplace record (a `--plugin-dir` checkout) gets a WARN
  line instead of a guess.
- **The commit guard is held back while it would refuse the adoption commit.** `.claude/settings.json`
  is not in the default `git.main_direct_paths`, so a guard installed before that commit would refuse
  the commit init asks for. Init holds the guard while any file it wrote is uncommitted and outside
  `main_direct_paths`, says so, and installs it on the next run. That is why the views' `.gitignore`
  goes in the backlog folder, under the main-direct `docs/`, and not at the root. Widening the
  default instead was considered and left alone: `main_direct_paths` is also the default
  `docs_lane_prefixes`. On a fresh repo the walk is `/lanes:init`, the `git add` and `git commit` it
  prints, `/lanes:init` again, and `/lanes:doctor` reads 16 ok, 0 warn. `tests/test_init.py` walks it
  end to end against a fake plugin install and asserts no doctor line is WARN or FAIL, before and
  after the first issue is committed through the guard.

## 0.4.48 — the hold is a debrief, written before the harness's end-of-turn box (2026-10-19)

- **The hold's verification steps were being lost to the harness** (LANES-51). The operator's
  harness gained an end-of-turn tool: a next-step box holding a recap of a few sentences and
  one question, with the contract that a box carrying a question ends the turn and nothing is
  written after it. The hold is a turn that ends on a question for the operator, so a model
  that followed the harness closely put "ready to verify" in the box and stopped: no debrief,
  no verification steps, slice after slice. `worktree-increment` step 5 had said only "announce
  readiness and what verification will cover", and the shape of the steps lived in one
  machine's memory, not in the skill.
- **Step 5 is now "Hold — the debrief", and the debrief is its deliverable:** the verdict
  against the baseline, numbered verification steps for every lane (the file or path, one
  runnable command, the output as observed by running it first, an expected refusal shown as
  its message and never a traceback), and what is uncommitted and where. It is written as a
  message in the transcript BEFORE any wrap-up, next-step or end-of-turn call the harness
  provides; the box carries the question, the message carries the debrief. Step 6.5's test
  cases are those steps refreshed after the rebase and rebuild. A ground rule says the same
  for anything the operator is handed to read or run. The incident is in
  `worktree-increment/references/incidents.md` ("The debrief that ended in the box"), and
  `tests/test_skills.py` pins the wording.

## 0.4.47 — the Privacy section says what the plugin does now (2026-10-17)

- **The README's Privacy section was still the one written for 0.4.9, and it was false**
  (LANES-50). It said "no network calls" and that the only outbound action was a `git push` the
  skills ask you to authorize. 0.4.9 had no script that touched a remote. Since then, eight do:
  the pull, issue numbering, the split, the claim, the close, the push guard and the landing fetch
  from or push to `origin`, and the release script pushes tags. The skills push a claim, a topic
  branch and a backlog-only commit without asking (LANES-5). `/lanes:doctor` and the landing ask
  the plugin's own repository for a release tag (LANES-33). `session-startup` installs four git
  hooks (LANES-1, LANES-11). Each was disclosed in its own README section, but the Privacy section
  denied them, and that section is the one a reader takes as the plugin's statement of what it
  does.
- **The section now lists everything:** what it reads (including the plugin registry the doctor
  compares against), both network destinations and the calls made to each, which pushes wait for
  an OK and how `git.land_requires_ok` and `git.ok_free_paths` change that, the four hooks with
  what each runs, what each refuses to overwrite and how to turn it off, and the local effects:
  worktree and branch removal after a landing, temporary worktrees, and the `127.0.0.1`-only
  served view. No behavior changed.

## 0.4.46 — a partial landing closes its issue and files the rest; the split is one command (2026-10-14)

- **A partial landing no longer sends its issue back to the queue** (LANES-47). `worktree-increment`
  step 9.1 said a partial goes "back to the status it should now carry with Current status saying
  where it stopped", and that sentence produced a story worked in four phases that never closed:
  its status section stacked four lanes of history, and the rest of the work could not be claimed,
  prioritized or dated piece by piece. Now a lane that lands part of its issue narrows the
  Resolution to what landed, marks it `verified` like any landing, and files the remainder as new
  issues in the same commit. Only a lane that lands nothing goes back to the queue. The incident
  is in `worktree-increment/references/incidents.md` ("The story that never closed").
- **An issue bigger than one landing is split before its lane starts.** `session-startup` step 8b
  says so when it resolves a directive: phases or parts in the text, independent deliverables,
  more than one session's work. The slice claims the children; an epic is never claimed.
- **`backlog_split.py <ID> "<child>" … --reported-by=…` and `/lanes:split`.** One command for
  the split that took a type edit, one mint per child and a status rewrite by hand. An open,
  blocked or paused issue becomes the epic, its children are minted under it with the parent's
  project, priority and assignee, and its Current status gains one line naming them. An epic only
  gains children. A claimed issue of this machine's is the partial landing: an epic can never be
  claimed or verified, so the issue does not become one. The remainder goes under the issue's own
  epic, or under a NEW epic minted over it, and the issue gets `epic:` and closes as that epic's
  first child, its claim untouched. Refused: verified or closed issues, another machine's claim,
  an unknown ID. A failure part-way restores the issue and removes what was minted. `--dry-run`
  prints the IDs; `--push` (main clone, main branch, checked before anything is written) commits
  every file by path and pushes under the OK-free guard. The command fills each child's Context
  from the parent's.
- **No `--check` finding for "phase N" in a Current status.** The issue asked for one if it was
  cheap and quiet. Measured against the project it came from, it tripped six live issues
  (a bootcamp's "step 3", a skill's "Step 6", a reference to another epic's "phase 2"), and a
  `--check` failure blocks every push, so it is not built.

## 0.4.45 — an issue goes in at the front of a lane, not into a lane of its own (2026-10-14)

- **`lanes_claim.py <ID>… --next-in <LANE>`** (LANES-49). `--behind` only appends, so an issue
  found mid-slice that had to be worked before the reserved ones was claimed bare, which opened
  a lane of its own and split one slice across two cards in the view (readlines' INFRA-111
  slice, 2026-10-12, regrouped by hand-editing `lane:` lines). `--next-in` takes a lane key or
  any member's ID, landed ones included. Each new ID is claimed `RESERVED`, queued behind what
  the lane's first reservation was queued behind, and that reservation is re-queued behind the
  last new ID, so the view reads head, new, old next, the rest. It reads the lanes with the
  view's own grouping (`backlog_index.lanes_in_flight`), so "next" means what the view shows.
- **It also moves an issue claimed into the wrong lane.** An ID this machine claimed in a lane
  of its own takes the target's `lane:` and keeps its state; a `RESERVED` one is re-queued, an
  `ACTIVE` or `PENDING` one moves only into a lane with nothing being worked and must be named
  first. A lane holding more than one claimed issue moves only when every one is named.
- **Refusals:** a lane not in flight; any live member, or a moved ID, whose marker another
  machine wrote (the only markers rewritten are this machine's own); an ID already in the lane;
  and the plain claim's refusals. Nothing is written on a refusal, and a concurrent change to
  the re-queued reservation withdraws the claim like a change to a claimed ID. A marker names a
  machine, not a session: a second session on the same machine is kept off another session's
  lane by the protocol's rule, as everywhere else, not by this check.
- **No doctor warning for one machine holding two lanes.** The issue floated one; it would fire
  all day, because several sessions on one machine legitimately run a lane each, and the doctor
  cannot tell sessions apart. `worktree-increment`'s scope section now says where a mid-slice
  issue goes (`--next-in` or `--behind`, never a bare claim); `session-startup` step 8b, the
  `/lanes:claim` command and the README name the option.

## 0.4.44 — required Resolution lines, configured per project (2026-10-14)

- **`[[backlog.required_lines]]`: a Resolution line `--check` requires, configured per project**
  (LANES-48). The built-in `Docs:` line made the doc loop a gate rather than a discipline; a
  project now names more lines the same way — a `Toggle:` line on every story, so "every feature
  ships behind a toggle" is enforced instead of remembered. Each rule is a `label`, an optional
  `projects` / `types` scope (omitted = every one; an empty list is an error, not a rule that
  matches nothing) and a required `since` cut-over. It binds every verified issue in scope while
  it is in force, and every issue closed `done` on or after `since` — the closed half is what
  reaches a hand-closed epic, which never passes through `verified`; nothing closed before
  `since` is ever checked. The line reads `<label>: <value>` or `<label>: none — <reason>`,
  bare, bolded or bulleted, or a label alone over a bulleted list; present but empty fails, and
  so does `none` with no reason. The backfill, and so the landing's own close, will not close an
  issue that owes one, for the reason it will not close an undocumented one: it runs before
  `--check`, and the closed issue it would write fails every check after. `/lanes:doctor` gains a
  `required lines` row naming `Docs:` and each rule, its scope and whether it is in force yet;
  the config check fails a rule with no `label` or `since`, a malformed date, a label with a
  colon, a duplicate, `Docs` itself, or a project or type the backlog does not have.
  `Docs:` stays built in: its condition is the change's paths, not the issue's project and type,
  so it shares the line pattern (`line_re`) rather than becoming a configured instance.
  `templates/config.toml` carries a commented example; the README, `session-startup` step 2d and
  `worktree-increment` step 9.1 say what the gate now covers.

## 0.4.43 — a due date on an issue, and the views open with the calendar (2026-10-11)

- **`due: YYYY-MM-DD` on an issue; a Due section at the top of every view** (LANES-46). One
  optional frontmatter key, written only when set (like `epic`): the date the issue stops being
  movable — a deadline, a dated event. A target the operator would merely like to hit stays
  priority. `backlog_new.py --due` (and `/lanes:new … --due=`) writes it after `opened`; an
  existing issue takes it by a frontmatter edit. `--check` validates the shape alone — a real
  calendar date — and an overdue live issue is a report finding, never a failed push. The HTML
  view, `INDEX.md` and `--report` all open with **Due**: every dated live or verified issue in
  calendar order with a countdown (`in 15d`, `today`, `3d OVERDUE`), above the lanes, because a
  date on the calendar outranks a lane; a closed issue drops out. The HTML view adds `Due` as a
  sortable column in the queue, flags overdue rows, counts `due` / `overdue` in the stat chips, and
  the Due table's rows are not double-counted by the filter. `session-startup`'s Brief carries
  one line for anything overdue or due within seven days, from the report's `DUE` block.

## 0.4.42 — the pull regenerates the bookmarked view itself (2026-10-10)

- **`lanes_pull.py` refreshes the main clone's view after every sync** (LANES-40). The sync is an
  `update-ref`, an index reset and a file checkout — never a merge or a rewrite — so the view hooks
  `post-merge` and `post-rewrite` never fire for it, and `post-checkout` fires only when a path was
  checked out: a sync the mirror had delivered in full checks out nothing, and the bookmark kept its
  pre-sync header. Reproduced on a Mac the same day: after a nine-commit fast-forward the view
  still read the old tip, and a landed, closed lane was read as active off the bookmark. The pull
  now makes the same `refresh_main_view` call the hooks make, once the sync has moved the branch,
  and says so (`pull: backlog view refreshed (…)`); off under `backlog.view_mode = "serve"` and in
  a repo with no backlog dir; a refresh that fails never fails the sync. Tests: a sync the mirror
  delivered in full (`0 path(s) checked out`) still re-renders the view with the new tip's stamp.

## 0.4.41 — the repository is LF everywhere (2026-10-10)

- **`.gitattributes`: `* text=auto eol=lf`, `*.png binary`** (LANES-41). The lanes repo had no
  attributes file, and a Windows clone has `core.autocrlf=false` by default, so a file rewritten
  there with CRLF — an ad-hoc `write_text()`, an editor save — would have committed as a whole-file
  diff (the LANES-39 lane caught 8 files, 2,889 insertions / 2,865 deletions for a 32-line change,
  only because the stat was read before the commit) and handed every Mac checkout the same diff
  back. Now every text file is LF in the index and in every working tree, whichever machine wrote
  it; the icon is the one binary. No tracked file carried CRLF at 0.4.40, so no renormalize commit
  was needed, and `test_ci.py` guards the file and the index from here on. No behavior change.

## 0.4.40 — a guard that cannot ask git refuses (2026-10-10)

- **`guard_position.py` and `guard_commit.py` fail closed when git itself cannot run** (LANES-42).
  Both guards' git helper returned `None` for "git is not on PATH / not executable / hung" exactly
  as for "not a git repository", and the caller read `None` as "no repo here" and ALLOWED — so a
  hook whose PATH had no git (the hook's PATH can differ from the interactive shell's, LANES-32)
  waved through a code write in the main clone on `main`, the one write the guard exists to
  refuse; LANES-18's probe on a Windows machine with no git on PATH answered `ALLOW: no git
  repository visible from the target`. The launcher was fixed for the same shape in LANES-17 (a
  Python it cannot run exits 2); the guards now do the same one layer down: git that cannot run
  raises `GitUnavailable`, the position guard answers `BLOCK` (exit 2) and the commit guard refuses
  the commit, each naming the cause and the `--explain` form. For the position queries (the
  `rev-parse` calls) a non-zero exit is also a refusal unless git said "not a git repository" —
  `fatal: detected dubious ownership` is not "no repo". An ordinary non-zero answer elsewhere
  (`git config --get` of an unset key) is unchanged. `--install` and `--status` report a git they
  cannot run and exit 1. Tests: a PATH without git, a git that exits 128 for another reason, and
  the one answer that still passes ("not a git repository"), for both guards and for `--explain`.

## 0.4.39 — a landing on Windows runs from the main clone (2026-10-10)

- **`lanes_land.py --path <worktree>`, and on Windows a refusal from inside the lane** (LANES-44).
  0.4.38 moved the script's own cwd out of the worktree before the clean-up, and both landings
  after it on a Windows machine still ended at exit 2, `failed to delete … Permission denied`:
  the shell that launches the script — the session's Bash call, the operator's PowerShell — keeps
  the worktree as ITS current directory for as long as it lives, and Windows refuses to delete any
  process's cwd, so from inside the lane the clean-up can never succeed there (an `exec` in that
  shell did not help either; the harness's own process tree held it, and a PowerShell removal from
  elsewhere succeeded at once). The script now takes `--path <worktree>` so it can run from the
  main clone, and on Windows a run from inside the worktree is refused up front, before anything
  is pushed, naming the `--path` form to use — a landing that then fails its own clean-up, every
  time, is worse than one that says which shape to run. `--keep` and `--dry-run` remove nothing
  and still run from anywhere; the dry run prints the note. The tests run each platform's real
  form (POSIX from inside the worktree, Windows from the main clone with `--path`) plus the
  refusal, the `--path` landing and the keep/dry-run cases with the platform forced either way —
  in-process the script's own `chdir` is the only cwd there is, which is exactly why the live
  failure never showed in the suite. `worktree-increment` step 9.7 and the README show both forms.

## 0.4.38 — the suite runs green on Windows (2026-10-10)

- **21 Windows reds at 0.4.36, none of them the protocol** (LANES-39). The suite had only ever
  run on macOS; the first run on a Windows machine failed 21 of 395. Four causes, three of
  them in the tests: `tests/conftest.py`'s `git()` and two calls in `test_guard_commit.py`
  ran `subprocess` with `text=True` and no `encoding`, so git output carrying an em dash (a
  commit subject, an issue title) decoded as cp1252 and the reader thread died
  (`UnicodeDecodeError … byte 0x8f`, surfacing as `AttributeError: 'NoneType' … strip`) —
  that alone was 11 of the 21; `test_backlog_index` filtered `resolution_problems()` paths
  with a `/` pattern that never matches a Windows path. One was real: **`lanes_land.py` exits 2
  on Windows after every landing** because its own process was launched from inside the
  worktree it then removes — the `git worktree remove` subprocess ran with the main clone as
  cwd, but Windows refuses to delete any process's current directory, so the clean-up failed
  with `Permission denied` after the landing had already happened. It now `os.chdir`s to the
  main clone first. One more decode fixed in passing: the view header's git helper in
  `backlog_index.py` had no `encoding`, so a tip commit with an em dash would have crashed the
  view on Windows. Every `text=True` subprocess call in `scripts/` and `tests/` now names
  `utf-8`.

## 0.4.37 — the pull reads a mirror-delivered tree before refusing (2026-10-10)

- **`lanes_pull.py` replaces the bare `git pull` in every skill** (LANES-38). A directory that is
  both git-tracked and mirrored by a file-sync client receives a landing's bytes before the next
  pull, so every other machine sees modified and untracked files that are byte-identical to
  origin, and `git pull --rebase` refuses on "unstaged changes". The first session on a second
  certifying machine sat 318 commits behind on exactly that, and the tool-permission classifier
  refused the hand fixes (`reset --hard`, a pointer-only `update-ref`) as destructive. The script
  fetches, compares each dirty path to `origin/<main>` by blob hash (through the path's clean
  filters, so a line-ending phantom counts as identical), reconciles the identical ones **without
  writing them** — the branch ref moves and only the index resets, so the mirror sees no change and
  nothing ripples back to the other machines — checks out only what origin changed that the mirror
  had not delivered, carries a new local file origin lacks as untracked, and refuses only on a path
  that genuinely differs, naming each one. Local commits are rebased first in a throwaway worktree
  so the dirty tree is never asked to be clean; a conflict aborts and moves nothing. `--ff-only`
  refuses local commits (the increment's step-1 pull), `--dry-run` prints the plan, `ORIG_HEAD` is
  set as a pull would. A stash was ruled out: it deletes the untracked files for a moment and the
  mirror propagates that delete. `session-startup` step 2, `worktree-increment` steps 1.1 and 10.3
  and `session-closeout`'s pre-landing pull all run it; `tests/test_skills.py` holds them to it.

## 0.4.36 — one marker, one reading (2026-10-10)

- **The view reads a claim header with a parenthesis in it** (LANES-37). `backlog_index.py`'s
  `MARKER_RE` closed the header at the first `)`, so a hand-written
  `(…, worktree readlines-lanes-36 + lanes-lanes-36 (lanes repo, off origin/next), branch …)` left it
  with no kind and the view rendered a live lane as `not started · claim time unreadable · UNKNOWN`,
  while `lanes_doctor.py`, which anchors on the date and reads the kind from the bold span, read the
  same marker as `ACTIVE LANE 9 min ago`. The header is now read up to the `) — **<kind>` that
  closes it.
- **A marker the view cannot read fails `--check`** (`unreadable_markers`). `orphaned_claims` only
  asked whether a marker was present; a present one that `parse_marker` rejects passed the gate
  while the view showed UNKNOWN. The view is the operator's whole picture of the lanes, so a
  marker no reader can parse is a failure, and the doctor's claim line says so too (`… by this
  reader, but the view cannot read the marker`) instead of reporting a lane the view does not show.

## 0.4.35 — one four-mode menu: Critical, Deep Dive, Housekeeping, Ops (2026-10-10)

- **One menu for every operator** (LANES-36). `session-startup` step 8 asks four options in a
  fixed order — **Critical** (urgent issues and blockers), **Deep Dive** (a single-context issue slice,
  project, or epic; research or spike), **Housekeeping** (issue-clearing, audits, and quick wins),
  **Ops** (decisions, accounts, and outreach) — and the line under each option is quoted from the
  skill's table verbatim, so the menu the operator sees and the rule the session follows cannot
  drift. The split is who does the work: Deep Dive and Housekeeping are the session's, Ops is the
  operator's with the session preparing and recording; urgency wins, so an Ops item with a deadline
  is Critical. The order is the recommended default for a long session. The non-code operator's
  menu (Authoring · Decisions · Quick wins) is gone: same four options, and their Deep Dive and
  Housekeeping proposals draw from docs-lane issues only.
- **Autonomous is retired.** Under `worktree-increment`'s rule 4 a session never opens a second
  issue while one waits on a verdict, and `git.land_requires_ok` makes every landing wait, so an
  "autonomous slice" was always one lane and then a stall. Unattended throughput is a protocol
  change, not a menu option. The rubric went with it.
- **The report is two headed sections, no numerals.** `Brief`, then `Sortable backlog`, then the
  mode question. Nothing mechanical read the `I —` / `II —` numerals.

## 0.4.34 — a lane lands on its own green (2026-10-08)

- **A clean rebase re-runs nothing** (LANES-34). `worktree-increment` 6.1 used to re-run
  `tests.rebase_rerun_command` (or the full suite) after every rebase onto a moved main branch, and
  `lanes_land.py` refuses a landing that is not a fast-forward, so each landing during a re-run forced
  another rebase and another run. As landings sped up, a lane could go round that loop indefinitely.
  Now a lane lands on its own step-4 full green plus a rebase with no hand-resolved logic conflict.
  Conflicts in the docs lane, the backlog, a changelog, a version string, or import lines where both
  sides were kept do not count. A logic conflict re-runs once, scoped as before; `main` moving during
  that run does not restart it. A composite break between two clean lanes is caught by the next full
  run at the new tip and fixed forward. The step-9 retry after a refused landing follows the same rule.
- `tests.rebase_rerun_command` keeps its name and format; it now runs only after a logic conflict.

## 0.4.33 — every release is tagged; an untagged pin does not land (2026-10-08)

- **The release mints its tag** (LANES-33). `scripts/release_tag.py --ensure --push` tags HEAD
  `lanes--v<version>` (annotated, with the release commit's subject) unless that version is
  already tagged on the remote. `.github/workflows/release-tag.yml` runs it on every push to
  `main` and `next`. It is a separate workflow from `ci.yml`, which cancels in-progress runs on
  `next`, and it does not wait for the tests. Releases 0.4.10 to 0.4.30 went out untagged after
  releases moved to `next` (LANES-14), so a consumer CI that checks out the pinned tag was red for
  about 250 pushes.
- **`lanes_land.py` refuses a pin to an untagged version.** A landing that moves
  `plugin_version` asks the plugin's remote (the manifest's `repository`) for the tag. It waits
  up to 90 seconds for the release CI to mint it, then refuses and touches nothing. A landing that
  leaves the pin alone asks nothing.
- **`/lanes:doctor` has a `release tag` check**: OK when the pin's tag is on the remote, WARN when
  it is not, SKIP when the remote cannot be asked.
- `LANES_RELEASE_REMOTE` overrides the remote both ask. Set but empty, it turns the lookup off
  (offline machines, tests).

## 0.4.32 — the backlog view is a bookmark (2026-10-08)

- **`backlog.view_mode = "file"` is the default** (LANES-11), replacing INFRA-43's served view. The
  operator bookmarks `file://<main clone>/<backlog.dir>/index.html`, and no server runs to show the backlog.
  `"serve"` keeps the old shape, and `session-startup` starts `--serve` only in that mode.
- **The view always lives in the main clone and renders its files**, from any checkout:
  `backlog_index.refresh_main_view()`. `backlog_index.py` run in a worktree writes and prints the main
  clone's view, never the worktree's.
- **Every backlog write regenerates it**: `backlog_new.py`, `lanes_claim.py` (claimed or restored),
  `push_guard.py --add`, the backfill and `--check`. An automatic refresh writes only where both views are
  gitignored, so it never leaves an untracked file for a broad `git add`.
- **`view_hooks.py`**: `post-merge`, `post-rewrite` and `post-checkout` blocks that regenerate the view after
  any pull, rebase or branch switch in the main clone. A fast-forward `pull --rebase` fires `post-merge`;
  one that replays local commits fires `post-rewrite`. Worktree checkouts and mid-rebase checkouts are
  ignored. The blocks **chain** after another tool's hook instead of refusing it (git-lfs writes two of the
  three); a non-shell hook, one that hands off with `exec`, and `core.hooksPath` are reported, not touched.
  `session-startup` installs them every session, beside the commit guard; `view_mode = "serve"` removes
  them. The doctor gains a `view hooks` check.
- The page header names the commit it was rendered from, and calls out a clone that is behind origin, in
  both modes.

## 0.4.31 — slice labels group by project (2026-10-08)

- **'/' within a project, ', ' between projects** (LANES-29). A slice of DOC-100 and PROD-19 was
  labelled `DOC-100/PROD-19`, which reads as one project. It is now `DOC-100, PROD-19`. Issues are
  grouped by project in order of first appearance, so DOC-100, PROD-19, DOC-103 reads
  `DOC-100/103, PROD-19`, the same label as DOC-100, DOC-103, PROD-19.
- An epic worked by several lanes now joins their names with `; ` (`▶ lane DOC-105, INFRA-101; PIPE-74`),
  since a lane name can now contain `, `.

## 0.4.30 — the lane row names the slice, not the worktree (2026-10-08)

- **The In progress row drops the worktree and branch names** (LANES-28) in `--report`, `INDEX.md` and
  the HTML card. `LANES-5/7/4/24 · readlines-lanes-4 + lanes-lanes-4 [lanes-4-work]` is now
  `LANES-5/7/4/24 · kyle-mac@… · claimed …`. The names meant nothing to the operator and, once a slice
  moved past its first issue, looked out of step with it. They stay in the ⏳ marker, where the doctor
  reads them as evidence. A lane with no worktree still says so: `worktree pending`, `between issues`,
  `not started`. `lane_label()` returns `phase` (None while an issue is being worked) in place of
  `where` and `branch`.

## 0.4.29 — retired operators (2026-10-08)

- **`retired = true` on an operator row** (plus optional `retired_on = "YYYY-MM-DD"`, LANES-27). A
  departure no longer forces a choice between deleting the row, which fails `--check` on every closed
  issue that names the person, and keeping it live, which still offers them for new work. A retired row:
  - grants nothing (a `certifies` or `may_edit_code` on it is a warning and is ignored) and never
    matches the running machine;
  - is not offered by `backlog_new.py` / `/lanes:new` (`--assignee`, `--reported-by`) or by `--report --who`;
  - validates on history: a closed or verified issue may name any short that is or was an operator,
    and `reported_by` accepts one on any issue, since who raised it doesn't change when they leave;
  - fails `--check` when a live issue is still assigned to it, with a "reassign live work" line.
- The doctor's `config` line counts retired rows (`2 operators + 1 retired (mike-win)`). A repo with only
  retired rows is in solo mode.

## 0.4.28 — the doctor checks every install scope (2026-10-08)

- **`version` reads every `installed_plugins.json` row that applies to the repo** (LANES-25): the
  user scope, plus project or local scope rows whose `projectPath` is this repo's main clone (so a
  worktree session counts the main clone's install). It warns on any row that differs from
  `plugin_version`, gives each its fix line (`claude plugin update lanes@<mkt> --scope <scope>`,
  then restart), and names the copy this session runs. A user-scope 0.4.21 beside a project-scope
  0.4.22 used to read `installed 0.4.22 == expected 0.4.22` while the session loaded 0.4.21.
- **`marketplace` compares every applicable scope's commit** with the marketplace clone's tip,
  instead of the first row it found.
- README: updating means every scope you installed.

## 0.4.27 — an epic reads in progress while a child is claimed (2026-10-08)

- **Derived, never written** (LANES-31). `backlog_index.epic_activity()` maps every live epic that
  has a claimed child, or a claimed child of a nested child epic, to the lanes doing the work.
  `--report`, the served view and `INDEX.md` show that epic as `in-progress`, with
  `▶ lane <slice>` in its row. The report's roll-up line gains `▶ IN PROGRESS: lane …`, the view's
  status pill carries a "derived" tooltip, and its status filter and sort follow the shown state.
  A closed epic keeps its own status.
- **Every lane names its epics** in the In progress block (report, view, INDEX.md), and the
  doctor's claim line ends with ` · epic <ID>`.
- **An epic is never a claim.** `lanes_claim.py` refuses an epic ID, and `--check` fails an epic
  with `status: in-progress`. Hand-marking one would read as a claim with no worktree, and go stale
  the moment the lane landed.

## 0.4.26 — the commit guard: the position rule at git's pre-commit (2026-10-08)

- **New `scripts/guard_commit.py`** (LANES-1). The edit-tool hook never sees a file written
  through Bash or a commit made from a terminal. The commit guard judges the STAGED SET of every
  commit with the same truth table: it refuses a commit on the main branch in the main clone
  that stages a path outside `git.main_direct_paths`, any commit in the main clone off the main
  branch (the incident shape, docs included), and any commit in a worktree that has the main
  branch checked out. A lane commit, and a claim or close on the main branch, pass. A rename
  counts as both its paths. During a rebase it judges the branch being rebased, not the
  detached HEAD.
- **Installed every session, no per-clone step.** `session-startup` step zero runs
  `guard_commit.py --install`, which is idempotent. It writes a `pre-commit` shim into
  `git rev-parse --git-path hooks`, shared by every worktree, and a plugin update re-points
  it. It never overwrites another tool's `pre-commit` and writes nothing under
  `core.hooksPath`; both are reported with the line to add by hand.
- **Fails open only on a stale path.** If the shim's launcher has vanished it allows the commit
  and says so, so a plugin update cannot block every commit in a repository. When no Python
  resolves, the launcher still refuses (LANES-17). `git commit --no-verify` bypasses the guard
  once; `git.commit_guard = false` (new key, default true) turns it off and makes `--install`
  remove the shim.
- **`/lanes:doctor` gains a `commit guard` line**: installed, stale, absent, another tool's hook,
  `core.hooksPath`, or off.

## 0.4.25 — startup asks what kind of session, then proposes 2–3 (2026-10-08)

- **`session-startup` steps 7–8 rewritten** (LANES-24). The five fixed blocks (Brief, view,
  Critical, Quick wins, one Recommended slice) became: the Brief and the view link, the
  **mode question**, then **2–3 proposals for that mode**, then stop. The operator usually
  acted on one block, so most of the analysis went into blocks nobody read, and a single
  slice could only be taken or overruled.
- **Critical is never dropped.** The Brief always carries `critical: N — <ID> …` (or
  `critical: none`), so a mode answer cannot hide a red canary row or a blocker.
- **The menu comes from the operator row**, with no new config key: a row that may edit code
  (and solo mode) gets Critical / unblocking · Quick wins · Deep · Autonomous; a non-code
  operator gets Authoring · Decisions · Quick wins. "Other" takes a project or an epic. A
  mode named in the trigger (`GA quick wins`) skips the question.
- **Autonomous has a rubric** until the backlog grows an `autonomy:` field: no operator
  decision in `blocked_on`, no visual or UX verdict, no legal or product judgment, and
  acceptance criteria a test can check. It also says to keep the machine awake.
- Unchanged: step 5b's exclusion set is built first and binds every proposal in every mode;
  identical titles; startup starts no work; 8a/8b.

## 0.4.24 — issue numbering sees the other machines (2026-10-08)

- **`backlog_new.py` fetches `origin` before it scans the refs** (LANES-4). `git log --all`
  saw only refs this clone had fetched, so an issue another machine pushed since the last
  fetch (a canary bug on its branch, the other operator's new issue) was invisible and its
  number could be minted twice. The fetch is bounded (20s, no credential prompt) and never
  prunes, because a deleted branch's refs keep a renumbered-away ID retired. A failed fetch
  prints one warning and numbers from the refs already here: minting still works offline.
  A clone with no `origin` is not a warning. `--no-fetch` skips the fetch on purpose.

## 0.4.23 — claims carry the machine; a lane can follow its operator (2026-10-08)

- **The doctor judges evidence by machine** (LANES-7). A marker already named its owner
  (`<Short>'s session on <machine id>@<host>`), but the stale-claim check counted "no
  worktree here" against every claim, and `git worktree list` sees one machine only. For a lane
  another machine owns, the pushed branch is now the only evidence. Its lines name the owner,
  and a stale-claim question is addressed to that machine's session. A same-named local
  worktree no longer counts for someone else's lane.
- **`lanes_claim.py --resume <ID>`** re-homes the operator's own ACTIVE lane to this machine. It
  refuses another person's lane, a lane this machine already owns, and a branch origin does
  not have (the branch is the hand-off). It makes the worktree from `origin/<branch>`,
  re-stamps the marker's time and machine (`Resumed from …`), and pushes under the OK-free
  guard.
- **`push_guard.py --ok-free` allows exactly that rewrite**: a marker by the same `short` on
  another machine, replaced in the same file by this machine's marker on the same branch.
  Every other edit to another machine's marker is still refused.
- **Skills:** startup's 5b evidence table splits ACTIVE lanes by owner machine;
  worktree-increment gains step 1r, resuming on another machine.

## 0.4.22 — a backlog-only push needs no OK, behind one guard (2026-10-07)

- **`scripts/push_guard.py`** (LANES-5). The claim push and the backfill close each carried
  their own copy of the "may this reach main without an OK" rule; every other backlog write
  (a staleness fix, a released claim, an issue minted mid-session) waited for the next OK'd
  push, invisible to other machines until then. One guard, two modes: `--ok-free` (every path
  ahead of origin under `git.ok_free_paths`, `--check` green, no commit edits a claim marker
  another machine wrote) and `--claim` (every path main-direct, unchanged). `--push` pushes and
  converges on a rejection by rebasing; `--add <paths> -m <subject>` commits exactly those
  paths first. `lanes_claim.py` and `backlog_index.py --backfill --push` now call it.
- **`git.ok_free_paths`**, default `[<backlog.dir>/]`. Deliberately not `main_direct_paths`:
  the standing docs change rules every session treats as ground truth, so they keep the OK.
  `[]` restores "every main-branch push waits for an OK".
- **The claim-marker check sees machines, not sessions.** A marker names
  `<Short>'s session on <machine>@<host>`; an edit to one naming another machine is refused.
  Two sessions on one machine share the id, so that half of "never write to another
  session's claim" stays a prohibition in the skills.
- **`backlog_new.py --push`** commits the minted issue alone and publishes it; refused from a
  lane worktree before anything is minted. **`/lanes:new`** publishes after writing the
  Context, through `push_guard.py --add`, in the main clone only.
- **Skills:** the branch-policy sections name the rule once; startup's staleness fix,
  worktree-increment's ACTIVE flip and closeout's release of unreached claims publish through
  the guard. The backfill close's guard skips the `--check` leg: a SKIPPED verified issue
  leaves `--check` red and must not hold back the closes that are right.

## 0.4.21 — /lanes:new mints an issue the operator raises (2026-10-07)

- **`/lanes:new`** (LANES-2). It runs `backlog_new.py` through the launcher, then reads the
  minted file back and writes its Context from what the operator said, so it ends as a filled
  issue rather than a stub. It takes the script's form (`<PROJECT> "<title>" [options]`) or plain
  prose; for prose it picks the project and title, says which, and asks when no project fits.
  It never commits or pushes. `allowed-tools` pre-approves exactly that one script.
- **`backlog_new.py --reported-by=me`** resolves to this machine's operator short. It is
  explicit, not a default, so the "no default reporter" rule holds. A machine with no
  operator row in a multi-operator repo is refused rather than guessed. `/lanes:new` passes
  it; a session raising an issue on its own still passes `--reported-by=claude`.

## 0.4.20 — the doctor reads a paraphrased claim kind, and warns on a missing one at once (2026-10-07)

- **The kind opens the bold span** (LANES-19). `lanes_doctor.py` read a claim's kind only when
  it was the whole bold span (`**ACTIVE LANE.**`), so paraphrased markers like
  `**ACTIVE LANE — readlines leg.**` or `**RESERVED, NOT STARTED — queued behind LANES-3**`
  read as kind-less. The views' marker parser already accepted them, so the two disagreed. The
  doctor now matches the kind as the span's prefix, the way the views do.
- **A kind-less marker warns at any age.** It used to pass under the 15-minute floor as "live
  by rule" and warn only at minute 15. A marker is written whole, kind included, so a young one
  without a kind is a misspelling, not a lane still setting up.
- The templates stay exact. `KIND_TEMPLATE_RE` keeps the old spelling, and `test_skills.py`
  holds the skills' markers to it, so the leniency applies only to reading.

## 0.4.19 — the landing's close runs off origin, past a busy main clone (2026-10-07)

- **`backlog_index.py --backfill --push --isolated`** (LANES-23). Closes and pushes from a
  throwaway worktree detached at a freshly fetched `origin/<main>`, then removes it. The main
  clone's branch, index and files are never touched, so another session's claim, committed
  there and not yet pushed, no longer makes the close refuse on the divergence. That refusal is
  what the first real `lanes_land.py` landing hit. A close that cannot push is discarded with
  the worktree; it is deterministic, so the next backfill redoes it. `--isolated` without
  `--push` is refused.
- **`lanes_land.py` closes with `--isolated`.** The main clone no longer fast-forwards to the
  close as part of the landing; it shows the close at its next pull. `worktree-increment` 9.7
  (and its by-hand form) and the README say so.
- Startup and closeout keep the in-place `--backfill --push`. Startup runs it right after its
  own pull so everything downstream reads the closed state, and closeout runs it in a clone
  it has just reconciled.

## 0.4.18 — lanes are recorded, named after their slice, and checked (2026-10-07)

- **`lane:` frontmatter** (LANES-10). `lanes_claim.py` writes `lane: <lead-ID>@<YYYY-MM-DD>` on
  every issue of a slice, and a `--behind` extension copies the extended lane's value. Behind a
  claim made before the field existed it derives the key the views derive from the marker
  (`<ID>@<claim date>`), so old and new claims group as one lane. The field STAYS on an issue
  that lands, as the record of which lane resolved it; closeout's release (and a partial going
  back to the queue) deletes it with the ⏳ marker.
- **A lane stays whole until its last issue lands** (Kyle). Its landed issues show beside the live
  ones (✓ landed / ✓ closed, full titles, landed first), and the lane disappears from the views
  only when none of its issues is in progress.
- **A lane is named after its slice**: `LANES-20/21/9`, the lead's full ID then the others'
  numbers in slice order (`LANES-22/INFRA-100` across projects). The lead comes from the
  recorded key, so the name holds after the lead lands and only reservations remain. The
  worktree and branch move into the card's detail line.
- **`--report` and `INDEX.md` open with In progress**, grouped by lane like the HTML view, and a
  claimed issue is listed once, under its lane, not again in the queue. `session-startup`
  block I lists in-flight work one line per lane.
- **`--check` lane rules**: a `lane:` on an open, blocked or paused issue, a value that is not
  `<ID>@<YYYY-MM-DD>`, or two ACTIVE/PENDING issues in one lane. A lane with none is legal
  (between two issues of a slice), and so is an in-progress issue without the field: claims
  made before 0.4.18 are grouped from their markers, and only the owning session may write to
  a claim.
- The view's card is named from the lane's ACTIVE/PENDING issue rather than its first one, so
  a slice whose lead has landed shows where work actually is.

## 0.4.17 — the backlog view, redesigned, with lanes on top (2026-10-07)

- The view (`index.html` and `--serve`) is laid out again (LANES-22).
  - **In progress, grouped by lane, at the top.** One card per lane: worktree, branch, machine,
    how long ago it was claimed, then its issues in slice order as active / pending / reserved.
    Lanes are read from the ⏳ claim markers (`queued behind <ID>` joins a reservation to its lead).
    A reservation whose lead is no longer claimed says so. A claimed issue appears once, in its
    card, not again in the queue. This is LANES-10's view half; its `lane:` field follows LANES-9.
  - **Title is the second column**, and blocked-on sits under it on one clamped line with the full
    text on hover. It no longer gets a column that wrapped rows to nine lines. `Opened` left the
    live table; `Age` sorts the same way.
  - **The filters fold behind a `Filters` button** with a count of active filters, and the chosen
    open/closed state is remembered per browser. Project chips show live counts.
  - **A one-line header** with stat tiles (live, in progress, critical, verified, closed). The
    generated-file note moves to a footer. On `--serve`, the clone position sits in the header when
    level and becomes a callout when behind.
  - **Backlog problems are a collapsed callout**, one per line, in the file view too. Before, they
    were one paragraph, and only on `--serve`.
  - Designed for light and dark, and for a phone: secondary columns drop below 720px and the page
    never scrolls sideways.
- Fix: a repo with no epics no longer hides every row. The epic filter now passes when no epic
  row of chips exists.

## 0.4.15 — a lane's issue closes when it lands (2026-10-07)

- `lanes_land.py` closes the issue it just landed (LANES-21). After the landing reads back and the
  clean-up, it runs `backlog_index.py --backfill --push` in the main clone. The resolving hash is
  final at that point, so `verified` no longer waits a whole session for the next startup. The
  backfill's own guards hold: it fast-forwards first, refuses off the main branch, and pushes only
  backlog-only commits. A close that cannot push exits 2 and is left to startup. `--no-close` skips
  it, and nothing runs for `--onto` another branch.
- `session-closeout` step 2 sweeps `--backfill --push` (or `--commit`, where a backlog-only push
  needs an OK) for lanes landed by hand or by another session. `session-startup` step 2d is the
  backstop.
- All three skills: housekeeping that needs no OK (the backfill, branch and claim pushes) is done and
  reported, never offered as a question.

## 0.4.14 — land, verify, then clean up (2026-10-07)

- New `scripts/lanes_land.py`: `worktree-increment` step 9.7's landing and step 10's clean-up as
  one operation (LANES-20). It refuses, touching nothing, from the main clone, on the main branch,
  with a dirty tree or on a machine that does not certify. It checks the fast-forward, pushes
  `<branch>:<main>`, re-fetches and requires HEAD on `origin/<main>`, and only then removes the
  worktree and deletes the branch, locally and on origin. The remote branch is kept if it carries
  commits that did not land. Exit 1 = not landed, nothing changed; 2 = landed, a named clean-up
  step left. `--keep`, `--dry-run`, and `--onto <branch>` for a repo that integrates on a branch
  other than `git.main_branch`.
- A session had run the landing and the clean-up on one line joined by `;`. The fast-forward lost a
  race with another session's push, nothing landed, and the clean-up deleted the worktree and the
  branch on both sides anyway.
- `worktree-increment` step 10: a branch, local or remote, is deleted only after it has **landed**,
  never because it was pushed. The landing and the clean-up are never one command line. The
  recovery path (`git fsck --unreachable --no-reflogs`) is in the incident.
- `session-closeout` step 3 carries the same branch rule.

## 0.4.16 — claim the slice mechanically (2026-10-07)

- New `scripts/lanes_claim.py` and `/lanes:claim`: `session-startup` 8b and `worktree-increment`
  step 1's claim as one all-or-nothing operation (LANES-9). It fetches and fast-forwards the main
  clone, then refuses unless every named ID has a file on `origin/<main>`. A missing ID is named
  with the refs where it does exist. It also refuses any ID that is `in-progress`, `verified`,
  `closed` or has uncommitted changes. It writes `status: in-progress` and the marker on every ID:
  the first `WORKTREE PENDING` with `--files`, each later one `RESERVED, NOT STARTED` behind the
  one before. Timestamps are local, the spelling is exactly what the doctor reads, and a prior
  `blocked`/`paused` status is noted. Then it runs `--check`, makes one commit by explicit path,
  applies the main-direct guard and pushes. A rejected push rebases; a concurrent change to one of
  the claimed issues withdraws the claim. `--behind <ID>` extends a lane, `--dry-run` prints the
  markers. Exit 1 = nothing written, 2 = committed but not pushed.
- `session-startup` 8b and `worktree-increment` step 1 call it instead of describing the edit. The
  startup skill's own example of the RESERVED marker misspelled it for the doctor, and a session
  copied it; that example is gone.

## 0.4.15 — a lane's issue closes when it lands (2026-10-07)

- `lanes_land.py` closes the issue it just landed (LANES-21). After the landing reads back and the
  clean-up, it runs `backlog_index.py --backfill --push` in the main clone. The resolving hash is
  final at that point, so `verified` no longer waits a whole session for the next startup. The
  backfill's own guards hold: it fast-forwards first, refuses off the main branch, and pushes only
  backlog-only commits. A close that cannot push exits 2 and is left to startup. `--no-close` skips
  it, and nothing runs for `--onto` another branch.
- `session-closeout` step 2 sweeps `--backfill --push` (or `--commit`, where a backlog-only push
  needs an OK) for lanes landed by hand or by another session. `session-startup` step 2d is the
  backstop.
- All three skills: housekeeping that needs no OK (the backfill, branch and claim pushes) is done and
  reported, never offered as a question.

## 0.4.14 — land, verify, then clean up (2026-10-07)

- New `scripts/lanes_land.py`: `worktree-increment` step 9.7's landing and step 10's clean-up as
  one operation (LANES-20). It refuses, touching nothing, from the main clone, on the main branch,
  with a dirty tree or on a machine that does not certify. It checks the fast-forward, pushes
  `<branch>:<main>`, re-fetches and requires HEAD on `origin/<main>`, and only then removes the
  worktree and deletes the branch, locally and on origin. The remote branch is kept if it carries
  commits that did not land. Exit 1 = not landed, nothing changed; 2 = landed, a named clean-up
  step left. `--keep`, `--dry-run`, and `--onto <branch>` for a repo that integrates on a branch
  other than `git.main_branch`.
- A session had run the landing and the clean-up on one line joined by `;`. The fast-forward lost a
  race with another session's push, nothing landed, and the clean-up deleted the worktree and the
  branch on both sides anyway.
- `worktree-increment` step 10: a branch, local or remote, is deleted only after it has **landed**,
  never because it was pushed. The landing and the clean-up are never one command line. The
  recovery path (`git fsck --unreachable --no-reflogs`) is in the incident.
- `session-closeout` step 3 carries the same branch rule.

## 0.4.13 — doctor checks the settings file and the marketplace source (2026-10-07)

- The single `settings` check is now three (LANES-16).
  - `settings` warns when the tracked `.claude/settings.json` differs from HEAD.
    `claude plugin marketplace remove` empties it, and the old check caught that only when the edit
    happened to remove `enabledPlugins`.
  - `settings lanes` checks that lanes is enabled and its marketplace declared, in HEAD as well as in
    the working tree. A committed regression is reported as committed.
  - `marketplace` compares this machine's registered source (repo, ref) with the declared one, and
    the installed commit with the marketplace clone's tip. No fetch is made. This is what would have
    flagged a machine still installing from `main` after the repo moved to `next`.
- The doctor now reads Claude Code's plugin state: `LANES_PLUGINS_DIR` if set, else the directory
  above the plugin's own cache path, else `$CLAUDE_CONFIG_DIR/plugins`, else `~/.claude/plugins`.

## 0.4.12 — backfill on concurrent certifying machines (2026-10-07)

- `--backfill` closes deterministically. `closed:` is the resolving commit's committer date
  (it used to be the day the backfill ran), and `commit:` is a fixed 7-character abbreviation
  (git's default length scales with each clone's object count). Two machines closing the same
  issue now write byte-identical files (LANES-6).
- New `--backfill --push`. It fetches and fast-forwards the main branch before scanning, commits,
  and pushes, but only when every commit ahead of origin touches the backlog dir alone. On a
  rejected push it re-fetches and rebases: an identical close merges cleanly or drops out, a real
  conflict aborts the rebase and leaves the commit local. It never forces. Several certifying
  machines may run it at once, so no machine has to be named the single writer.

## 0.4.11 — one person, two machines (2026-10-07)

- Operator rows may share a `short`. A row is a machine (`id` and the `(name, platform)` pair stay
  unique); `short` is the person, so one person on two machines is two rows with one short. 0.4.10
  and earlier rejected that as a duplicate, which left a second machine with no permissions or a
  fake second assignee. Assignees, reporters, the certifier label and the default assignee list each
  person once (LANES-3).

## 0.4.10 — fail closed without a working Python (2026-10-07)

- Every hook, command and skill runs its script through the new `scripts/lanes.sh`, never a bare
  `python3`. On Windows `python3` can be the Microsoft Store alias, which exits 49; for a `PreToolUse`
  hook any exit but 2 allows the call, so the position guard failed **open** on such a machine, and a
  missing `python3` (127 / 9009) failed open the same way. The launcher takes the first of
  `$LANES_PYTHON`, `python3`, `python`, `py` that proves it is Python 3.11+ (the scripts need
  `tomllib`), and exits **2** when none does. A set `LANES_PYTHON` that does not work is an error,
  never silently replaced. It runs only a script in its own directory.
- The hook command ends `|| exit 2`: if `sh` itself is missing, or the guard crashes, the write is
  blocked rather than allowed.
- `commands/doctor.md` and `commands/init.md` pre-approve the launcher form of their one script.
- `tests/test_ci.py` follows `ci.yml`'s `branches: [main, next]`.

## 0.4.9 — listing links (2026-10-04)

- README gains a Privacy section: what is read (`git config user.name`, the platform, the repo's own
  lanes config, `CLAUDE_PROJECT_DIR`), and that nothing leaves the machine.
- CI runs on pushes to `main` and on pull requests, not on tag pushes: a release tag points at a commit
  `main` has already run, so every `claude plugin tag --push` was buying a second identical run.
- `plugin.json` carries `homepage` and `repository` so the directory listing has somewhere to point.
  The form also suggests `documentationUrl` and `supportUrl`, but `claude plugin validate --strict`
  (2.1.289) rejects both as unknown fields, so they stay out until the CLI's schema knows them.

## 0.4.8 — directory review, third pass (2026-10-04)

- `guard_position.py` reads each of its eight variables by literal name; the previous loop over a tuple
  read as "a variable named at run time".
- `session-closeout` 1b: the per-worktree checks are written with the skills' `<placeholder>` convention,
  no shell variables; the directory reads any `$` in a skill's command as a command assembled at run time.

## 0.4.7 — directory review, second pass (2026-10-04)

- `guard_position.py` reads the eight variables it needs by name (`os.getenv`), never the whole
  environment: the directory read a whole-environment enumeration beside a runtime-assembled shell line in
  `session-closeout` as "a credential leaving the machine in two steps". Neither half ever did that; now
  neither half is there.
- `session-closeout` 1b: the worktree sweep pipes `git worktree list` into `while read`, no `$(...)`.
- No file names the icon by path (the directory holds a plugin whose text references an image an
  interpreter could be pointed at). The size-band test went with it; the directory enforces that band.

## 0.4.6 — the icon (2026-10-04)

- The listing icon: a trunk that becomes the arrow, two lanes that leave it and rejoin it at
  different heights, and a third that ends in a square — drawn as outlines, amber on dark. The vector
  source is `assets/icon.svg`; the PNG is rendered from it at 1024 px.

## 0.4.5 — first directory submission (2026-10-04)

- The hook command ends `|| exit 2`: if `sh` itself is missing, or the guard crashes, the write is
  blocked rather than allowed.
- `commands/doctor.md` and `commands/init.md` pre-approve exactly the script each runs
  (`Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<script>":*)`), not every `python3` command — the
  directory's policy check held the broad form.
- `userConfig.worktree_root` removed from the manifest: declared since 0.4.0, read by nothing, and the
  directory's credential check reads a declared-but-unused option as a hand-off. A key returns the day
  a script reads it.
- A listing icon (1024 px): the directory fixes it at the first submission, so it ships before one.
  `tests/test_listing.py` pins the first two.

## 0.4.4 — CI green (2026-10-04)

- Frontmatter is now strict YAML: `worktree-increment`'s description carried a `: ` ("the full
  lifecycle: claim → …") and both commands' `argument-hint` began with `[`, which a strict parser reads
  as a flow sequence. The runtime tolerated all three; `claude plugin validate --strict` in CI did not,
  while the same CLI version on the author's machine never descended into the components. Values quoted.
- `tests/test_skills.py::test_plugin_validates_strict` skipped on the wrong signal: a missing executable
  is a `FileNotFoundError`, not "command not found" on stderr. Now `shutil.which`. The pytest job installs
  the CLI so CI runs the test instead of skipping it.
- The validator targets are the repo root and the two manifests. A bare `skills` / `commands`
  directory is read as a plugin root on the runner ("No manifest found"), and which target descends
  into the components differs between machines on the same CLI version; the three named cover it.

## 0.4.3 — CI (2026-10-04)

- `.github/workflows/ci.yml`: pytest plus `claude plugin validate --strict` on every push and pull
  request. The validator is run once per target (`plugin.json`, `marketplace.json`, `skills/`,
  `commands/`): on the author's machine a run on the repo root checked only the marketplace manifest,
  so each target is named rather than trusting how a given build resolves a directory. `tests/test_ci.py`
  pins the shape.
- The first consumer retires its own copies of `backlog_index.py` / `backlog_new.py` the same day
  (its INFRA-67); its CI checks this repo out and runs the plugin's `--check --root .`.

## 0.4.2 — second-adopter fixes, continued (2026-10-04)

- `/lanes:init` and `/lanes:doctor` name the exact gitignore shape when `.claude/` is excluded
  wholesale: `.claude/*` plus `!.claude/settings.json` and `!.claude/lanes/` — git cannot re-include a
  file whose parent directory is excluded, which the first wording did not say.
- README: install from the main clone, never from a worktree (a project-scope install records the
  absolute path it was run from).

## 0.4.1 — second-adopter fixes (2026-10-04)

- `git.main_direct_paths` defaults to `["docs/", ".claude/lanes/", "*.md"]`. Found on the second
  adopter: with the lanes directory outside the default list, adopting the plugin was itself a
  write the position guard refuses in the main clone, so the first lane had to be the adoption.
  The lanes files are process docs; they belong with `docs/`.
- `/lanes:doctor` gains a `views` check: the generated `INDEX.md` / `index.html` must be gitignored
  (the second adopter had no such rule).
- `/lanes:init` keeps warning when `.claude/` is gitignored wholesale (the second adopter's case);
  the fix it names is two negation rules (`!.claude/settings.json`, `!.claude/lanes/`).

## 0.4.0 — the hook and the marketplace (2026-10-04)

- `hooks/hooks.json` + `scripts/guard_position.py` — the position guard as a `PreToolUse` hook on
  `Write|Edit|MultiEdit|NotebookEdit`: refuses a write that would land in the main clone OR on the
  main branch, allows exactly the lane shape and the claim shape. `git.main_branch` and
  `git.main_direct_paths` are read from the TARGET repo's `.claude/lanes/config.toml` (defaults
  otherwise). **Scoped to the repo the session started in** (`$CLAUDE_PROJECT_DIR`): a write into a
  different repository is allowed as foreign — the first consumer's copy refused every write into
  this plugin's own repo while the plugin was being built from a session there.
- `.claude-plugin/marketplace.json` — the repo doubles as its own marketplace (`"source": "."`):
  `claude plugin marketplace add <owner>/lanes` then `claude plugin install lanes@lanes-marketplace`.
- `tests/test_guard_position.py` — truth table through a fake environment, the hook contract,
  config binding, the foreign-repo rule, and the real git path with a second repository.

## 0.3.0 — the protocol skills (2026-10-04)

- `skills/session-startup`, `skills/worktree-increment`, `skills/session-closeout` — the three
  skills, layer-separated: protocol in `SKILL.md`, bindings read from the config
  (`git.main_branch`, `backlog.dir`, `tests.command`, `tests.rebase_rerun_command`,
  `worktrees.port_command`, `operators[]`, `lanes.*`), local facts delegated to the three
  extension points (`preflight.md` after the pull, `lane-setup.md` after `git worktree add`,
  `pre-land.md` before the landing OK). Every two-operator step says what solo mode does.
- `skills/*/references/incidents.md` — every rule's incident, dated, operators anonymized to roles,
  mechanics kept.
- `tests/test_skills.py` — the portability gate: no name of the source project, its people, its
  machines or its local tooling may appear in a skill; marker vocabulary agrees with the doctor.

## 0.2.0 — the tracker (2026-10-04)

- `scripts/backlog_index.py` — the file-based backlog: local views (`INDEX.md` + sortable
  `index.html`), `--report`, `--check` (structure, claim/marker agreement, commit-citation
  ancestry, verified-issue resolvability, the `Docs:`-line doc-loop gate, epic parents,
  resolution/status agreement), `--backfill` (close verified issues by the commit subject they
  cite; refused on a machine whose operator row does not certify), `--serve` (re-parses on every
  request). Every table it reads comes from the config, resolved once at import into module
  globals; `--root` points it at another repository.
- `scripts/backlog_new.py` — mint an issue with the next free ID across the local tree AND every
  ref (two worktrees cannot mint the same number); enums from the config; `--reported-by` required.
- `/lanes:doctor` now runs `backlog_index.py --check` whenever the backlog directory exists.
- Config: `backlog.docs_lane_prefixes` entries are a directory prefix (`docs/`), a root glob
  (`*.md`) or an exact path; `backlog.resolution_required_from` omitted means always required.
- Dropped from the source project's copies, not ported: the positional-queue cutover artifacts
  (`_review`, `owner:`, `legacy_ref`), hard-coded operator names, the port-constant import.

## 0.1.0 — skeleton (2026-10-03)

- `.claude-plugin/plugin.json` manifest.
- Config schema: `.claude/lanes/config.toml`, every key optional, defaults mean **solo mode**.
  Loader in `scripts/lanes_config.py` (stdlib only, `tomllib`, Python 3.11+).
- `/lanes:init` — scaffolds `config.toml` + the three extension-point stubs
  (`preflight.md`, `lane-setup.md`, `pre-land.md`).
- `/lanes:doctor` — config valid, installed vs expected plugin version, extension-point
  files present, backlog `--check` (when the tracker ships), stale-claim candidates older
  than the 15-minute floor (reported as questions, never edited).
- Not yet in this version: the backlog scripts, the three protocol skills, the position-guard
  hook, `marketplace.json`. See README → Roadmap.
