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


def test_plugin_validates_strict():
    """A missing executable is a FileNotFoundError from subprocess, never a
    "command not found" on stderr -- the first CI run died on exactly that."""
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not on PATH")
    done = subprocess.run(["claude", "plugin", "validate", "--strict", str(ROOT)],
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stdout + done.stderr
