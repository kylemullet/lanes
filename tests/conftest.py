import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


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
