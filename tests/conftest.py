import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _no_real_plugins_dir(tmp_path_factory, monkeypatch):
    """The doctor reads Claude Code's plugin state (LANES-16); a test never sees this machine's."""
    monkeypatch.setenv("LANES_PLUGINS_DIR", str(tmp_path_factory.mktemp("plugins")))


@pytest.fixture(autouse=True)
def _no_release_tag_lookup(monkeypatch):
    """The landing and the doctor ask the plugin's remote for a pin's release tag (LANES-33);
    a test never reaches the network. Set and empty, the lookup is off; a test that wants it
    points LANES_RELEASE_REMOTE at a local bare repo."""
    monkeypatch.setenv("LANES_RELEASE_REMOTE", "")


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo with one commit on `main` and a known user."""
    root = tmp_path / "proj"
    root.mkdir()
    git("init", "-q", "-b", "main", cwd=root)
    git("config", "user.email", "t@example.com", cwd=root)
    git("config", "user.name", "Tester", cwd=root)
    (root / "README.md").write_text("# proj\n", encoding="utf-8")
    git("add", "README.md", cwd=root)
    git("commit", "-q", "-m", "init", cwd=root)
    return root


def write_issue(root, backlog_dir, project, issue_id, status, body):
    d = root / backlog_dir / project
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{issue_id}-thing.md"
    p.write_text(
        f"---\nid: {issue_id}\nproject: {project}\ntype: story\nstatus: {status}\n---\n\n"
        f"# {issue_id} — thing\n\n## Context\n\nx\n\n## Current status\n\n{body}\n\n## Resolution\n\n(stub)\n",
        encoding="utf-8",
    )
    return p
