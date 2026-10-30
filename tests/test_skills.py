"""The three protocol skills: present, well-formed, and free of the source project.

The extraction's criterion is portability. A skill that still names the project it came
from, its operators, its machines, its data mirror or its local scripts is a fork with
extra steps, so this gate greps for every such name. Incident references may describe
the mechanics of what happened, but operators are roles there too.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ("session-startup", "worktree-increment", "session-closeout")

# Names of the project this was extracted from, its people, machines and local tooling.
FORBIDDEN = re.compile(
    r"Kyle|Mike\b|readlines|relined|kyle-mac|mike-win|kyle-win|Zephyr|odafc|ODA\b|"
    r"Google Drive|\bdrive/|lane_port|rebase_impact|corpus_manifest|suite_canary|"
    r"dedupe_drive|run-local|frontend/dist|modules/|PROJECT_STATE|patent"
)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_exists_with_frontmatter(name):
    text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    fm = text.split("---\n", 2)[1]
    assert f"name: {name}\n" in fm
    assert re.search(r"^description: .{80,}", fm, re.M), "the description is what triggers the skill; make it specific"
    assert "references/incidents.md" in text, "every rule's incident lives in the reference file"
    assert (ROOT / "skills" / name / "references" / "incidents.md").is_file()


@pytest.mark.parametrize("name", SKILLS)
def test_skill_is_free_of_the_source_project(name):
    for rel in ("SKILL.md", "references/incidents.md"):
        text = (ROOT / "skills" / name / rel).read_text(encoding="utf-8")
        hits = sorted({m.group(0) for m in FORBIDDEN.finditer(text)})
        assert not hits, f"{name}/{rel} still names the source project: {hits}"


@pytest.mark.parametrize("name", SKILLS)
def test_skill_binds_to_config_and_plugin_root(name):
    text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/" in text, "scripts are referenced through the plugin root"
    assert re.search(r"scripts/backlog_index\.py(?! \S*--)", text) is None or "${CLAUDE_PLUGIN_ROOT}" in text
    for key in ("main_branch", "backlog.dir", "tests.command"):
        assert key in text, f"{name} must bind to config key {key}"
    assert ".claude/lanes/" in text, "every skill reads its extension point"


def test_each_skill_names_its_extension_point():
    text = (ROOT / "skills/session-startup/SKILL.md").read_text(encoding="utf-8")
    assert "preflight.md" in text
    text = (ROOT / "skills/worktree-increment/SKILL.md").read_text(encoding="utf-8")
    assert "lane-setup.md" in text
    text = (ROOT / "skills/session-closeout/SKILL.md").read_text(encoding="utf-8")
    assert "pre-land.md" in text


def test_two_operator_steps_say_what_solo_mode_does():
    text = (ROOT / "skills/session-startup/SKILL.md").read_text(encoding="utf-8")
    assert text.lower().count("solo mode") >= 4
    assert "no-op" in text


def test_incidents_carry_dates():
    for name in SKILLS:
        text = (ROOT / "skills" / name / "references" / "incidents.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## .+$", text, re.M)
        assert len(headings) >= 6, name
        undated = [h for h in headings if not re.search(r"\(\d{4}-\d{2}-\d{2}", h)]
        assert not undated, f"{name}: incidents without a date: {undated}"


def test_claim_marker_vocabulary_is_shared_with_the_doctor():
    """The skills WRITE the markers the doctor READS; the three strings must agree."""
    import lanes_doctor as ld
    text = (ROOT / "skills/worktree-increment/SKILL.md").read_text(encoding="utf-8")
    for kind in ("WORKTREE PENDING", "RESERVED, NOT STARTED", "ACTIVE LANE"):
        assert kind in text
        assert ld.KIND_RE.search(f"**{kind}.**"), kind


def test_landing_runs_through_the_land_script_and_never_shares_a_line_with_clean_up():
    """LANES-20: a `;` ran the clean-up after a landing that lost the fast-forward race."""
    text = (ROOT / "skills/worktree-increment/SKILL.md").read_text(encoding="utf-8")
    assert 'scripts/lanes.sh" lanes_land.py' in text
    assert "Never join the landing and the clean-up" in text
    assert "deleted only when the SECOND passes: landed" in text
    assert (ROOT / "scripts" / "lanes_land.py").is_file()


def test_the_landed_issue_closes_on_landing_and_closeout_sweeps():
    """LANES-21: verified issues waited a whole session for the next startup."""
    inc = (ROOT / "skills/worktree-increment/SKILL.md").read_text(encoding="utf-8")
    assert "closes the issue that just landed" in inc
    assert "done and reported, never offered" in inc
    close = (ROOT / "skills/session-closeout/SKILL.md").read_text(encoding="utf-8")
    assert "backlog_index.py --backfill --push" in close and "never offered" in close
    start = (ROOT / "skills/session-startup/SKILL.md").read_text(encoding="utf-8")
    assert "**The backstop.**" in start


def test_the_hold_is_a_debrief_written_before_the_harness_box():
    """LANES-51: a harness end-of-turn box swallowed the hold's verification steps."""
    text = (ROOT / "skills/worktree-increment/SKILL.md").read_text(encoding="utf-8")
    assert "### 5. Hold — the debrief" in text
    assert "for every lane, not only UX-touching work" in text
    assert "as observed by running it first" in text
    assert text.count("BEFORE any wrap-up") == 2, "the ground rule and step 5 both say where the debrief goes"
    inc = (ROOT / "skills/worktree-increment/references/incidents.md").read_text(encoding="utf-8")
    assert "## The debrief that ended in the box (2026-10-19)" in inc


def test_claims_run_through_the_claim_script():
    """LANES-9: a hand-made claim skipped an ID and copied a marker the doctor cannot read."""
    import lanes_doctor as ld
    for name in ("session-startup", "worktree-increment"):
        text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert 'scripts/lanes.sh" lanes_claim.py' in text, name
        # every bold claim kind a skill spells out must be one the doctor recognizes
        for m in re.finditer(r"\*\*(WORKTREE PENDING|RESERVED, NOT STARTED|ACTIVE LANE)[^*]*\*\*", text):
            assert ld.KIND_TEMPLATE_RE.fullmatch(m.group(0)) and ld.KIND_RE.match(m.group(0)), f"{name}: {m.group(0)}"


def test_plugin_validates_strict():
    """A missing executable is a FileNotFoundError from subprocess, never a
    "command not found" on stderr -- the first CI run died on exactly that."""
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not on PATH")
    done = subprocess.run(["claude", "plugin", "validate", "--strict", str(ROOT)],
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stdout + done.stderr


# --- startup asks the mode, then proposes (LANES-24) -----------------------------------------

def _startup():
    return (ROOT / "skills" / "session-startup" / "SKILL.md").read_text(encoding="utf-8")


def test_startup_always_carries_the_critical_line():
    """No mode answer may hide an urgent item: the Brief carries it whatever the mode. Since
    LANES-67 the script renders it, first, and the session's judgment goes in as arguments."""
    text = _startup()
    assert "`🔴 **Critical (N)** — <item>`" in text and "`🟢 **Critical** — none`" in text   # LANES-73's spelling
    assert "no mode answer can hide it" in text


def test_startup_asks_the_mode_with_one_four_option_menu_and_no_fixed_blocks():
    """LANES-36: one menu for every operator, four options in a fixed order, Autonomous retired."""
    text = _startup()
    menu = [
        ("Critical", "Urgent issues and blockers"),
        ("Deep Dive", "A single-context lane of issues, a project, or an epic. Research or spike."),
        ("Housekeeping", "Issue-clearing, audits, and quick wins"),
        ("Ops", "Decisions, accounts, and outreach"),
    ]
    rows = [f"| **{opt}** | {line} |" for opt, line in menu]
    for row in rows:
        assert row in text, row
    assert [text.index(r) for r in rows] == sorted(text.index(r) for r in rows)   # the order is the rule
    for retired in ("**Autonomous**", "**Authoring**", "**Quick wins**", "**Decisions**",
                    "**Critical / unblocking**", "**Deep (epic or project)**"):
        assert retired not in text, retired
    assert "One menu for every operator" in text and "`may_edit_code`" in text  # non-code: same menu, docs-lane picks
    assert "GA housekeeping" in text                                    # a mode named in the trigger
    assert "five blocks" not in text and "five-block" not in text
    assert "**III — Critical" not in text and "**V — Recommended slice" not in text


def test_startup_report_is_two_headed_sections_without_numerals():
    """LANES-36: `Brief` and `Sortable backlog` as plain headers, no `I —` / `II —`, then the question."""
    text = _startup()
    assert "**Brief.**" in text and "**Sortable backlog.**" in text
    assert "**I — Brief" not in text and "**II — Sortable" not in text and "block II" not in text


def test_startup_proposals_keep_the_invariants():
    text = _startup()
    assert "2–3, never one" in text
    assert "no `in-progress` issue, nothing in the exclusion set, in any mode" in text
    assert "Then STOP and wait." in text
    assert "Autonomous was retired" in text                           # and its rubric went with it
    assert "acceptance criteria a test can check" not in text


def test_every_main_branch_pull_runs_through_the_pull_script():
    """LANES-38: a bare `git pull` refused on a tree a file-sync mirror had already updated,
    and the session could not clear it. The script reconciles; the skills must run it."""
    for name in SKILLS:
        text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert 'scripts/lanes.sh" lanes_pull.py' in text, name
        assert not re.search(r"^git pull", text, re.M), f"{name}: a bare `git pull` as a command"
    assert "lanes_pull.py --ff-only" in (ROOT / "skills/worktree-increment/SKILL.md").read_text(encoding="utf-8")
    assert "never substitute `git stash`" in _startup().lower()
    assert (ROOT / "scripts" / "lanes_pull.py").is_file()


# --- vocabulary (LANES-57) -----------------------------------------------------------------

# Where the protocol speaks to the operator: the skills, commands, README, templates and the
# scripts' help and messages. CHANGELOG is history and keeps its words.
_PROSE = ["skills", "commands", "templates", "scripts", "README.md"]


def _prose_files():
    for top in _PROSE:
        p = ROOT / top
        yield from ([p] if p.is_file() else sorted(q for q in p.rglob("*") if q.suffix in (".md", ".py", ".toml")))


def test_the_protocol_says_lane_not_slice():
    """A claimed group of issues is a lane (LANES-57). The one 'slice' left is quoted, and
    means something else: a project's scoped test re-run."""
    allowed = {'was followed by a "slice" of 101 test files'}
    hits = []
    for f in _prose_files():
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bslices?\b", line, re.I) and not any(a in line for a in allowed):
                hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert hits == [], "\n".join(hits)


def test_startup_and_shutdown_read_as_sequences_and_keep_their_identifiers():
    """LANES-57: the operator reads 'startup sequence' and 'shutdown sequence'; the skill
    names stay `session-startup` and `session-closeout`, which every trigger and doc uses."""
    start = (ROOT / "skills/session-startup/SKILL.md").read_text(encoding="utf-8")
    stop = (ROOT / "skills/session-closeout/SKILL.md").read_text(encoding="utf-8")
    assert "\nname: session-startup\n" in start and "\n# Startup sequence\n" in start
    assert "\nname: session-closeout\n" in stop and "\n# Shutdown sequence\n" in stop
    assert "The startup sequence:" in start.split("---", 2)[1]
    assert "The shutdown sequence:" in stop.split("---", 2)[1] and '"shutdown"' in stop.split("---", 2)[1]
    for f in _prose_files():
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"\bsession (startup|closeout)\b", text, re.I), f
        assert not re.search(r"\bclose-?outs?\b", re.sub(r"session-closeout", "", text), re.I), f


def test_the_lane_works_from_the_acceptance_criteria_and_fills_their_test_ids():
    """LANES-60: the lane writes the rows before building, reports them at the hold, and lands
    with every row carrying its Test ID or a manual check by its owner."""
    text = (ROOT / "skills/worktree-increment/SKILL.md").read_text(encoding="utf-8")
    work = text.split("### 3. Work the item", 1)[1].split("### 4.", 1)[0]
    hold = text.split("### 5. Hold", 1)[1].split("### 6.", 1)[0]
    final = text.split("1. Final backlog pass", 1)[1].split("**A lane that lands part", 1)[0]
    for step in (work, hold, final):
        assert "Acceptance criteria" in step
    assert "Test ID" in work and "Test ID" in final


def test_startup_asks_the_project_beside_the_mode_in_one_dialog():
    """LANES-64: the project question rides in the mode question's dialog, offers "Any project"
    and the report's top three, narrows the proposals outside Critical, and never the Brief."""
    text = _startup()
    step8 = text.split("### 8. Ask the mode and the project, then propose 2–3", 1)[1].split("### 8a.", 1)[0]
    assert "the mode first, the project second, in ONE call" in step8
    assert "| **Any project** | Proposals from the whole backlog |" in step8
    assert step8.index("**The mode question.**") < step8.index("**The project question.**")
    assert "`PROJECTS` block" in step8 and "never re-rank them by judgment" in step8
    assert "Critical answers the project as well" in step8                  # Critical never asks it
    assert "which ignores the project answer" in step8                      # ...and ignores it in the dialog
    assert "no project answer removes an item from it" in step8             # the critical: line stands
    assert "`GA ui`" in step8 and "`GA deep dive CORE`" in step8            # triggers answer it
    assert "`backlog.projects` lists a single project, never" in step8
    assert "outside Critical, only from the chosen projects" in step8
    assert "which backlog project, in the same dialog" in text.split("---", 2)[1]
    assert "`PROJECTS` block is the project question's menu" in text       # step 5 points at it


def test_the_status_line_contract_reads_the_same_in_the_skill_the_template_and_the_readme():
    """LANES-66: one spelling for every check that reports into the Brief, said in the same
    words everywhere an author meets it, and step 7 sends every status line through the fold."""
    spelling = "<LEVEL> <name>: <detail>          LEVEL is OK, CUE or CRITICAL; the name has no colon"
    meaning = "`OK` means nothing to read. `CUE` is worth a glance and is never a finding."
    for rel in ("skills/session-startup/SKILL.md", "templates/preflight.md", "README.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert spelling in text and meaning in text, rel
    step7 = _startup().split("### 7. Render the Brief", 1)[1].split("### 8.", 1)[0]
    assert 'scripts/lanes.sh" lanes_brief.py' in step7 and "status_lines.py" in step7   # the script folds (LANES-67)
    assert "an unmarked check is never folded out of sight" in step7
    for name in ("`pull`", "`doctor`", "`commit guard`", "`view hooks`", "`backfill`", "`backlog check`"):
        assert f"| {name} (step" in step7, name                     # the protocol's own checks are levelled
    assert "needs no Brief line" not in _startup()                   # superseded by the OK level


def test_the_brief_is_rendered_by_the_script_and_the_session_adds_only_judgment():
    """LANES-67: step 7 runs lanes_brief.py, shows its output as printed, and puts the
    session's judgment in --critical and --note; the old hand-written bullet list is gone."""
    step7 = _startup().split("### 7. Render the Brief", 1)[1].split("### 8.", 1)[0]
    assert "never write the Brief by hand" in step7
    assert "Paste\nit into your reply as printed and add nothing to it" in step7
    assert "**Your judgment goes in as arguments, and only there.**" in step7
    rows = ["`🔴 **Critical (N)** — <item>`", "`🟡 **<name>** — <detail>`", "`🕘 **Since HH:MM**`", "`📅 **Due this week** —",
            "`🔒 **Lanes (N)** —", "`⚠️ <note>`", "`🌿 **Branches** —", "`📦 **Landed** —", "`✅ **Health** — N ok`",
            "live · <X> <top priority>"]
    assert [step7.index(r) for r in rows] == sorted(step7.index(r) for r in rows)   # the order is the rule
    assert "Bullets, one line each" not in step7
    assert "git.permanent_branches" in _startup().split("### 2x.", 1)[0]          # step 2 names the key


def test_the_brief_is_markdown_bullets_and_the_judgment_is_one_clause_each():
    """LANES-73: the first pasted Brief was a code block the chat pane wrapped into a wall of
    monospace; the reply is Markdown bullets, and the session's arguments stay short."""
    step7 = _startup().split("### 7. Render the Brief", 1)[1].split("### 8.", 1)[0]
    assert "**Markdown, never a code block** (LANES-73)" in step7
    assert "**Markdown bullets, one item each**" in step7
    assert "**`--critical` and `--note` are one\nclause each**" in step7
    assert "never the OK checks' names" in step7 and "cut at a word boundary" in step7
    assert "code block" not in step7.split("**Markdown, never a code block**", 1)[0]   # the old container is gone
    assert "in a code block" not in step7.split("**Show it:", 1)[1]
    inc = (ROOT / "skills/session-startup/references/incidents.md").read_text(encoding="utf-8")
    assert "## The Brief that wrapped (2026-10-29)" in inc
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Markdown\nbullets" in readme and "the Brief in a code block" not in readme


def test_after_the_first_brief_step_7_says_only_what_changed_is_shown():
    """LANES-68: the saved Brief lives in the clone's git directory, the next run says what
    changed, and --full is the way back to everything."""
    step7 = _startup().split("### 7. Render the Brief", 1)[1].split("### 8.", 1)[0]
    assert "**After the first Brief, only what changed** (LANES-68)" in step7
    for phrase in ("inside the clone's git directory", "never tracked", "`since <HH:MM>: …`", "`nothing\nchanged`",
                   "`(was <LEVEL>)`", "`N in flight,\nunchanged`", "`--full` renders the\nwhole Brief"):
        assert phrase in step7, phrase


def test_the_brief_is_text_in_the_reply_before_the_question():
    """LANES-70: running the script showed the operator nothing; the session asked the mode
    question with the Brief still in a collapsed tool result."""
    step7 = _startup().split("### 7. Render the Brief", 1)[1].split("### 8.", 1)[0]
    step8 = _startup().split("### 8. Ask the mode", 1)[1].split("### 8a.", 1)[0]
    assert "Both are **text in your reply**" in step7
    assert "**Show it: running the script shows the operator nothing** (LANES-70)" in step7
    assert "before the question call" in step7 and "addressed to you, not to the\noperator" in step7
    assert "never in place of it" in step8 and "choose blind" in step8
    assert step7.index("**Show it:") < step7.index("**Sortable backlog.**")
    inc = (ROOT / "skills/session-startup/references/incidents.md").read_text(encoding="utf-8")
    assert "## The Brief behind the question (2026-10-28)" in inc


def test_an_unknown_machine_gets_the_doctors_advice_and_one_question_at_most():
    """LANES-71: step zero said "ask, do not guess" and gave no question, so the session
    asked a new operator which existing machine's setup to copy."""
    zero = _startup().split("## Step zero", 1)[1].split("## Procedure", 1)[0]
    assert "the\ndoctor's `machine` line says what settles it (LANES-71)" in zero
    assert "Ask that question and nothing else" in zero
    assert "🚫 **Never ask which existing machine's\nsetup to copy**" in zero
    assert "ask, do not\nguess" not in zero
    step7 = _startup().split("### 7. Render the Brief", 1)[1].split("### 8.", 1)[0]
    assert "| `machine` (step zero) | the doctor's `machine` line is `OK` |" in step7
    inc = (ROOT / "skills/session-startup/references/incidents.md").read_text(encoding="utf-8")
    assert "## The machine set up like someone else's (2026-10-28)" in inc
