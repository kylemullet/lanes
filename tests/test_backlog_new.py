"""Mint-time ID allocation -- the concurrent-worktree collision class.

`backlog_new.py` allocates the next ID from the union of the local glob and every
path ever seen on ANY ref. These tests build real temporary git repositories rather
than stubbing subprocess, because the property under test IS a git one: worktrees
share a refs/ namespace, so a sibling branch's issue files are reachable from a lane
that cannot see them on disk.
"""
import subprocess
import sys

import pytest

import backlog_index as bidx
import backlog_new as bn
import lanes_config as lc


@pytest.fixture(autouse=True)
def _vocab(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "git_user_name", lambda cwd=None: "Tester")
    raw = {"backlog": {"projects": ["INFRA", "UI", "PROD", "SYNTH"]},
           "operators": [
               {"name": "Tester", "platform": sys.platform, "id": "test-box", "short": "kyle",
                "certifies": True, "may_edit_code": True},
               {"name": "Other", "platform": "win32", "id": "other-box", "short": "mike",
                "certifies": False, "may_edit_code": False}]}
    for k, v in bidx.settings(tmp_path / "guard", raw).items():
        monkeypatch.setattr(bidx, k, v)
    monkeypatch.setattr(bn, "BACKLOG_REL", "docs/backlog")


def _git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8",
    )


def _issue(repo, project, num, slug="thing"):
    d = repo / "docs" / "backlog" / project
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{project}-{num}-{slug}.md"
    f.write_text(f"# {project}-{num}\n\n" + f"body for {project}-{num}\n" * 20)
    return f


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _issue(repo, "INFRA", 1)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "INFRA-1")
    return repo


def _point_at(monkeypatch, repo):
    monkeypatch.setattr(bn, "ROOT", repo)
    monkeypatch.setattr(bn, "BACKLOG", repo / "docs" / "backlog")
    monkeypatch.setattr(bidx, "ROOT", repo)
    monkeypatch.setattr(bidx, "BACKLOG", repo / "docs" / "backlog")
    monkeypatch.setattr(bidx, "INDEX", repo / "docs" / "backlog" / "INDEX.md")
    monkeypatch.setattr(bidx, "HTML_VIEW", repo / "docs" / "backlog" / "index.html")


def test_local_max_reads_the_working_tree(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    _issue(repo, "INFRA", 4)
    assert bn.local_max("INFRA") == 4


def test_refs_max_sees_an_id_committed_on_another_branch(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    _git(repo, "checkout", "-q", "-b", "lane-a")
    _issue(repo, "INFRA", 2)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "INFRA-2")
    _git(repo, "checkout", "-q", "-")
    assert not (repo / "docs/backlog/INFRA/INFRA-2-thing.md").exists()
    assert bn.local_max("INFRA") == 1
    assert bn.refs_max("INFRA") == 2
    assert bn.next_number("INFRA") == 3


def test_a_renamed_away_id_stays_retired(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    _issue(repo, "INFRA", 9)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "INFRA-9")
    _git(repo, "mv", "docs/backlog/INFRA/INFRA-9-thing.md", "docs/backlog/INFRA/INFRA-4-thing.md")
    _git(repo, "commit", "-qm", "renumber INFRA-9 -> INFRA-4")
    assert bn.local_max("INFRA") == 4
    assert bn.refs_max("INFRA") == 9
    assert bn.next_number("INFRA") == 10


def test_refs_max_ignores_other_projects(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    _issue(repo, "UI", 88)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "UI-88")
    assert bn.refs_max("INFRA") == 1
    assert bn.refs_max("UI") == 88


def test_refs_max_is_zero_for_an_unused_project(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    assert bn.refs_max("SYNTH") == 0


def test_refs_max_degrades_to_zero_outside_a_repo(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    (plain / "docs" / "backlog" / "INFRA").mkdir(parents=True)
    _point_at(monkeypatch, plain)
    _issue(plain, "INFRA", 6)
    assert bn.refs_max("INFRA") == 0
    assert bn.next_number("INFRA") == 7


def test_next_number_survives_git_being_absent(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    monkeypatch.setattr(bn.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("git")))
    assert bn.refs_max("INFRA") == 0
    assert bn.next_number("INFRA") == 2


def test_next_number_takes_the_union_not_either_alone(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    _git(repo, "checkout", "-q", "-b", "lane-a")
    _issue(repo, "INFRA", 5)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "INFRA-5")
    _git(repo, "checkout", "-q", "-")
    _issue(repo, "INFRA", 3)
    assert bn.local_max("INFRA") == 3
    assert bn.refs_max("INFRA") == 5
    assert bn.next_number("INFRA") == 6


def test_refs_max_reads_the_configured_backlog_dir(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    monkeypatch.setattr(bn, "BACKLOG_REL", "work/issues")
    monkeypatch.setattr(bn, "BACKLOG", repo / "work" / "issues")
    (repo / "work" / "issues" / "INFRA").mkdir(parents=True)
    (repo / "work" / "issues" / "INFRA" / "INFRA-7-x.md").write_text("x" * 100)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "INFRA-7 elsewhere")
    assert bn.refs_max("INFRA") == 7 and bn.local_max("INFRA") == 7


_EPIC_FM = """---
id: {iid}
project: {proj}
type: {type_}
status: open
priority: normal
blocked_on: null
assignee: kyle
opened: 2026-09-21
closed: null
commit: null
links: []
---

# {iid} — a parent
"""


def _parent(repo, iid, type_="epic"):
    proj = iid.split("-")[0]
    d = repo / "docs" / "backlog" / proj
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{iid}-parent.md").write_text(_EPIC_FM.format(iid=iid, proj=proj, type_=type_), encoding="utf-8")


def test_create_issue_writes_the_epic_line_after_links(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    _parent(repo, "PROD-1")
    path = bn.create_issue("PROD", "child", epic="PROD-1", regen_index=False)
    fm = path.read_text(encoding="utf-8").split("---")[1]
    assert "\nlinks: []\nepic: PROD-1\n" in fm


def test_create_issue_without_an_epic_has_no_epic_key_and_no_legacy_ref(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    path = bn.create_issue("PROD", "plain", regen_index=False)
    fm = path.read_text(encoding="utf-8").split("---")[1]
    assert "epic:" not in fm and "legacy_ref" not in fm


def test_create_issue_rejects_a_parent_that_does_not_exist(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    with pytest.raises(ValueError, match="does not exist"):
        bn.create_issue("PROD", "child", epic="PROD-9", regen_index=False)


def test_create_issue_rejects_a_parent_that_is_not_an_epic(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    _parent(repo, "PROD-1", type_="story")
    with pytest.raises(ValueError, match="not an epic"):
        bn.create_issue("PROD", "child", epic="PROD-1", regen_index=False)


def test_epic_type_is_mintable(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    path = bn.create_issue("PROD", "an umbrella", type_="epic", regen_index=False)
    assert "\ntype: epic\n" in path.read_text(encoding="utf-8")


def test_create_issue_writes_the_keys_in_their_fixed_positions_and_defaults_the_assignee(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    path = bn.create_issue("PROD", "attributed", assignee="mike", reported_by="claude", regen_index=False)
    fm = path.read_text(encoding="utf-8").split("---")[1]
    assert "\nblocked_on: null\nassignee: mike\nreported_by: claude\nopened:" in fm
    assert "\ncommit: null\nresolution: null\nlinks: []\n" in fm
    path = bn.create_issue("PROD", "defaulted", regen_index=False)
    assert "\nassignee: kyle\n" in path.read_text(encoding="utf-8")
    monkeypatch.setattr(bidx, "DEFAULT_ASSIGNEE", "mike")
    path = bn.create_issue("PROD", "defaulted again", regen_index=False)
    assert "\nassignee: mike\n" in path.read_text(encoding="utf-8")


def test_create_issue_rejects_unknown_reporter_assignee_or_resolution(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    for kw in ({"reported_by": "bob"}, {"assignee": "bob"}, {"resolution": "fixed"}):
        with pytest.raises(ValueError, match=list(kw)[0]):
            bn.create_issue("PROD", "x", regen_index=False, **kw)
    with pytest.raises(ValueError, match="project"):
        bn.create_issue("ZZ", "x", regen_index=False)


def test_create_issue_regenerates_the_views_in_the_configured_root(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    bn.create_issue("INFRA", "indexed", reported_by="kyle")
    assert (repo / "docs" / "backlog" / "INDEX.md").is_file()
    assert "INFRA-2" in (repo / "docs" / "backlog" / "index.html").read_text(encoding="utf-8")


def test_cli_requires_reported_by(monkeypatch, capsys):
    with pytest.raises(SystemExit) as e:
        bn.main(["INFRA", "unattributed"])
    assert e.value.code == 2
    assert "--reported-by" in capsys.readouterr().err


def test_cli_root_mints_into_another_repo(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    (repo / ".claude" / "lanes").mkdir(parents=True)
    (repo / ".claude" / "lanes" / "config.toml").write_text(
        '[backlog]\nprojects = ["INFRA", "UI"]\n', encoding="utf-8")
    assert bn.main(["--root", str(repo), "UI", "from the cli", "--reported-by", "claude"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("created docs/backlog/UI/UI-1-from-the-cli.md")
    text = (repo / "docs/backlog/UI/UI-1-from-the-cli.md").read_text(encoding="utf-8")
    assert "assignee: tester\n" in text   # solo mode in THAT repo: the git user, slugged


# --- --reported-by=me, what /lanes:new passes (LANES-2) ----------------------

def _mint_me(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    monkeypatch.setattr(bidx, "regenerate", lambda: None)
    return repo


def test_reported_by_me_is_this_machines_operator(tmp_path, monkeypatch, capsys):
    repo = _mint_me(tmp_path, monkeypatch)
    assert bn.main(["INFRA", "raised by hand", "--reported-by=me"]) == 0
    (minted,) = (repo / "docs/backlog/INFRA").glob("*-raised-by-hand.md")
    text = minted.read_text(encoding="utf-8")
    assert "\nreported_by: kyle\n" in text


def test_reported_by_me_is_refused_on_a_machine_with_no_row(tmp_path, monkeypatch, capsys):
    _mint_me(tmp_path, monkeypatch)
    monkeypatch.setattr(bidx, "MACHINE", {"id": "Stranger+linux", "short": "stranger", "known": False})
    with pytest.raises(SystemExit) as e:
        bn.main(["INFRA", "who said this", "--reported-by=me"])
    assert e.value.code == 2
    assert "has no operator row" in capsys.readouterr().err


def test_the_new_command_passes_me_and_fills_the_context():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "commands" / "new.md").read_text(encoding="utf-8")
    assert "--reported-by=me" in text and "--reported-by=claude" in text
    assert "Context" in text and "$ARGUMENTS" in text


# --- the scan fetches first: another MACHINE's pushed issue counts (LANES-4) ---------------

def _two_machines(tmp_path):
    """A bare origin holding INFRA-1, and two clones of it; clone B pushes INFRA-2."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    seed = _repo(tmp_path)
    _git(seed, "push", "-q", str(origin), "HEAD:refs/heads/main")
    a, b = tmp_path / "a", tmp_path / "b"
    _git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(a))
    _git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(b))
    _issue(b, "INFRA", 2, slug="from-the-other-machine")
    _git(b, "add", "-A")
    _git(b, "commit", "-qm", "INFRA-2")
    _git(b, "push", "-q", "origin", "main")
    return a


def test_refs_max_fetches_first_and_sees_an_issue_pushed_from_another_machine(tmp_path):
    a = _two_machines(tmp_path)
    assert bn.refs_max("INFRA", a, fetch=False) == 1            # the pre-LANES-4 view: never fetched
    assert bn.refs_max("INFRA", a) == 2


def test_create_issue_does_not_reuse_another_machines_id(tmp_path, monkeypatch):
    a = _two_machines(tmp_path)
    monkeypatch.setattr(bidx, "regenerate", lambda: None)
    path = bn.create_issue("INFRA", "minted here", reported_by="claude", backlog=a / "docs" / "backlog")
    assert path.name.startswith("INFRA-3-")


def test_a_failed_fetch_warns_once_and_still_mints(tmp_path, capsys):
    a = _two_machines(tmp_path)
    _git(a, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    assert bn.refs_max("INFRA", a) == 1
    err = capsys.readouterr().err
    assert err.count("warning: could not fetch origin") == 1


def test_no_origin_is_not_a_warning(tmp_path, capsys):
    repo = _repo(tmp_path)
    assert bn.refs_max("INFRA", repo) == 1
    assert capsys.readouterr().err == ""


def test_a_retired_operator_is_not_offered_for_new_issues(tmp_path, monkeypatch):
    """LANES-27: `--assignee` and `--reported-by` offer active operators only."""
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    monkeypatch.setattr(bidx, "ASSIGNEES", ("kyle", "shared"))
    monkeypatch.setattr(bidx, "REPORTERS", ("claude", "kyle"))
    for kw in ({"assignee": "mike"}, {"reported_by": "mike"}):
        with pytest.raises(ValueError, match=list(kw)[0]):
            bn.create_issue("PROD", "x", regen_index=False, **kw)
