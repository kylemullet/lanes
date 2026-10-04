"""The plugin's own CI gate stays what the README promises: pytest plus
`claude plugin validate --strict`, on every push, per target."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_exists():
    assert CI.is_file(), "lanes has no CI workflow"


def test_ci_runs_on_every_push_and_pull_request():
    text = CI.read_text(encoding="utf-8")
    assert "\n  push:\n" in text and "\n  pull_request:\n" in text


def test_ci_runs_the_suite_and_the_strict_validator_per_target():
    text = CI.read_text(encoding="utf-8")
    assert "python -m pytest -q tests/" in text
    for target in (".", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
        assert f"claude plugin validate --strict {target}" in text, (
            f"CI no longer validates {target} strictly -- which target descends into the "
            "components differs by environment, so all three are named")
    assert "validate --strict skills" not in text and "validate --strict commands" not in text, (
        "a bare component directory is read as a plugin root in CI (No manifest found)")
