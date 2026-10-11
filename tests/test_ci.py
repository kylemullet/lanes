"""The plugin's own CI gate stays what the README promises: pytest plus
`claude plugin validate --strict`, on every push, per target."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_exists():
    assert CI.is_file(), "lanes has no CI workflow"


def test_ci_runs_on_every_push_and_pull_request():
    text = CI.read_text(encoding="utf-8")
    assert "\n  push:\n    branches: [main, next]" in text and "\n  pull_request:\n" in text, (
        "CI runs on pushes to main and next and on PRs; a tag push re-runs a commit main already ran")


def test_ci_runs_the_suite_and_the_strict_validator_per_target():
    text = CI.read_text(encoding="utf-8")
    assert "python -m pytest -q tests/" in text
    for target in (".", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
        assert f"claude plugin validate --strict {target}" in text, (
            f"CI no longer validates {target} strictly -- which target descends into the "
            "components differs by environment, so all three are named")
    assert "validate --strict skills" not in text and "validate --strict commands" not in text, (
        "a bare component directory is read as a plugin root in CI (No manifest found)")


RELEASE = ROOT / ".github" / "workflows" / "release-tag.yml"


def test_every_push_to_main_or_next_tags_the_release():
    """LANES-33: twenty releases went out untagged and a consumer CI that checks out the
    pinned tag failed on every push. The tag is minted by CI, not by memory."""
    text = RELEASE.read_text(encoding="utf-8")
    assert "\n  push:\n    branches: [main, next]" in text
    assert "python3 scripts/release_tag.py --ensure --push" in text
    assert "contents: write" in text
    assert "cancel-in-progress: false" in text, (
        "a cancelled tag run is an untagged release; ci.yml cancels on next, this must not")
    assert "needs:" not in text, "the consumer installs from the branch; the tag cannot wait for the tests"


# --- line endings (LANES-41) -----------------------------------------------------

def test_gitattributes_pins_lf_and_marks_the_icon_binary():
    """A Windows clone has core.autocrlf=false by default; without this file a CRLF
    rewrite there commits as a whole-file diff and every other checkout gets it back."""
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    rules = [l.split() for l in text.splitlines() if l.strip() and not l.startswith("#")]
    assert ["*", "text=auto", "eol=lf"] in rules
    assert ["*.png", "binary"] in rules


def test_no_tracked_text_file_carries_crlf_in_the_index():
    out = subprocess.run(["git", "ls-files", "--eol"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    crlf = [line for line in out.splitlines() if line.startswith("i/crlf") or line.startswith("i/mixed")]
    assert not crlf, "renormalize these: " + "; ".join(crlf)
