"""What the plugin directory's submission checks hold us to (first submission 2026-10-04)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / ".claude-plugin" / "plugin.json"


def test_commands_pre_approve_only_the_script_they_run():
    """`Bash(python3:*)` was a policy hold: it pre-approves any python3 command."""
    for cmd in (ROOT / "commands").glob("*.md"):
        text = cmd.read_text(encoding="utf-8")
        m = re.search(r"^allowed-tools: (.*)$", text, re.M)
        assert m, f"{cmd.name}: no allowed-tools"
        for broad in ("Bash(python3:*)", "Bash(python:*)", "Bash(sh:*)", "Bash(*)"):
            assert broad not in m.group(1), f"{cmd.name}: broad shell pre-approval {broad}"
        # Through the launcher (LANES-17): `sh ".../scripts/lanes.sh" <script>.py`, one script each.
        scripts = re.findall(r'scripts/lanes\.sh" ([a-z_]+\.py):\*\)', m.group(1))
        assert scripts, f"{cmd.name}: allowed-tools names no script behind the launcher"
        for s in scripts:
            assert f'scripts/lanes.sh" {s} ' in text.split("---", 2)[2], (
                f"{cmd.name}: allowed-tools pre-approves {s} but the body never runs it")


def test_manifest_declares_no_unused_user_config():
    """`userConfig.worktree_root` was declared and read by nothing; the directory
    read the declaration as a credential hand-off. Declare a key only with a reader."""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for key in m.get("userConfig", {}):
        hits = [p for p in (ROOT / "scripts").glob("*.py") if key in p.read_text(encoding="utf-8")]
        assert hits, f"userConfig.{key} has no reader under scripts/"
