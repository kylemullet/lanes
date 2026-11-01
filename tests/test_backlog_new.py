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


def _ignore_views(repo):
    (repo / ".gitignore").write_text("docs/backlog/INDEX.md\ndocs/backlog/index.html\n", encoding="utf-8")


def test_create_issue_regenerates_the_views_in_the_configured_root(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _ignore_views(repo)
    _point_at(monkeypatch, repo)
    bn.create_issue("INFRA", "indexed", reported_by="kyle")
    assert (repo / "docs" / "backlog" / "INDEX.md").is_file()
    assert "INFRA-2" in (repo / "docs" / "backlog" / "index.html").read_text(encoding="utf-8")


def test_create_issue_leaves_no_view_where_the_views_are_not_ignored(tmp_path, monkeypatch):
    """An automatic refresh never leaves an untracked file for a broad add (LANES-11)."""
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    bn.create_issue("INFRA", "indexed", reported_by="kyle")
    assert not (repo / "docs" / "backlog" / "index.html").exists()
    assert "index.html" not in _git(repo, "status", "--porcelain", "-uall").stdout


def test_create_issue_in_a_worktree_refreshes_the_main_clones_view(tmp_path, monkeypatch):
    """The bookmark is the main clone's file, rendered from the main clone's files (LANES-11)."""
    repo = _repo(tmp_path)
    _ignore_views(repo)
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "lane")
    _point_at(monkeypatch, wt)
    monkeypatch.setattr(bidx, "REPO_NAME", wt.name)              # as a process started in the lane has it
    bn.create_issue("INFRA", "from the lane", reported_by="kyle")
    assert not (wt / "docs" / "backlog" / "index.html").exists()
    page = (repo / "docs" / "backlog" / "index.html").read_text(encoding="utf-8")
    assert "INFRA-1" in page and "from the lane" not in page    # the main clone's files, not the lane's
    # ...and the main clone's name in the header, not the worktree's (LANES-54)
    assert f"<title>Lanes | {repo.name} Backlog</title>" in page and "wt Backlog" not in page
    assert bidx.REPO_NAME == "wt", "the redirect is undone once the view is written"


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


# --- due dates (LANES-46) ---------------------------------------------------------

def test_create_issue_writes_due_after_opened_and_only_when_set(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "refresh_main_view", lambda auto=True: None)
    monkeypatch.setattr(bn, "ROOT", tmp_path)
    bl = tmp_path / "docs" / "backlog"
    p = bn.create_issue("UI", "dated", backlog=bl, opened="2026-10-11", due="2026-10-26", fetch=False)
    fm = p.read_text(encoding="utf-8").split("---")[1].strip().splitlines()
    assert fm.index("due: 2026-10-26") == fm.index("opened: 2026-10-11") + 1
    q = bn.create_issue("UI", "undated", backlog=bl, opened="2026-10-11", fetch=False)
    assert "due" not in q.read_text(encoding="utf-8").split("---")[1]
    with pytest.raises(ValueError, match="due '2026-13-01' is not a YYYY-MM-DD calendar date"):
        bn.create_issue("UI", "bad", backlog=bl, due="2026-13-01", fetch=False)


def test_cli_due_reaches_the_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bidx, "refresh_main_view", lambda auto=True: None)
    monkeypatch.setattr(bn, "ROOT", tmp_path)
    monkeypatch.setattr(bn, "BACKLOG", tmp_path / "docs" / "backlog")
    assert bn.main(["UI", "dated", "--reported-by=kyle", "--due=2026-11-20", "--no-fetch"]) == 0
    rel = capsys.readouterr().out.split("created ")[1].strip()
    assert "due: 2026-11-20\n" in (tmp_path / rel).read_text(encoding="utf-8")


def test_the_new_command_offers_due():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "commands" / "new.md").read_text(encoding="utf-8")
    assert "--due=YYYY-MM-DD" in text


# --- the Acceptance criteria table (LANES-60) ---------------------------------------------

SECTIONS = ["## Context", "## Acceptance criteria", "## Current status", "## Resolution"]


def test_a_new_issue_carries_the_acceptance_criteria_table_after_its_context(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    text = bn.create_issue("PROD", "with criteria", regen_index=False).read_text(encoding="utf-8")
    assert [l for l in text.splitlines() if l.startswith("## ")] == SECTIONS
    table = text.split("## Acceptance criteria", 1)[1].split("## Current status", 1)[0]
    assert ("\n| AC | Test case description | Owner | Test ID |\n| :-- | :-- | :-- | :-- |\n"
            "| AC1 | | | |\n") in table


def test_a_claim_on_a_new_issue_leaves_its_acceptance_criteria_alone(tmp_path, monkeypatch):
    import lanes_claim
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    text = bn.create_issue("PROD", "claimed", regen_index=False).read_text(encoding="utf-8")
    claimed = lanes_claim.with_claim(text, "⏳ IN-PROGRESS (the marker)", lane="PROD-1@2026-10-26")
    before_status = lambda t: t.partition("\n---\n")[2].split("## Current status", 1)[0]
    assert "| AC1 | | | |" in before_status(claimed) and before_status(claimed) == before_status(text)
    assert claimed.split("## Current status\n\n", 1)[1].startswith("⏳ IN-PROGRESS (the marker)\n")


def test_the_new_command_writes_acceptance_criteria_from_what_done_looks_like():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "commands" / "new.md").read_text(encoding="utf-8")
    assert "Acceptance criteria" in text and "Test ID" in text and "leave the table's stub" in text


# --- a finding logged mid-lane is minted on the main branch (LANES-63) --------------------

def _lane_repo(tmp_path, monkeypatch):
    """A repo with a lanes config (so --root re-reads it), one valid issue, and a worktree."""
    repo = _repo(tmp_path)
    (repo / ".claude" / "lanes").mkdir(parents=True)
    (repo / ".claude" / "lanes" / "config.toml").write_text(
        '[backlog]\nprojects = ["INFRA", "UI"]\n', encoding="utf-8")
    _git(repo, "config", "user.name", "Tester")       # the subprocess --check resolves the solo assignee from this
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "config")
    wt = tmp_path / "repo-lane"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "lane-work")
    monkeypatch.setattr(bidx, "regenerate", lambda: None)
    monkeypatch.setattr(bidx, "refresh_main_view", lambda: None)
    return repo, wt


def test_a_mint_in_a_lane_worktree_without_push_is_refused_and_names_the_fix(tmp_path, monkeypatch, capsys):
    """LANES-63: an issue minted in a worktree is on no ref until the lane lands, so another
    lane can take its number first. Refused, nothing written, --push and --in-lane named."""
    repo, wt = _lane_repo(tmp_path, monkeypatch)
    assert bn.main(["--root", str(wt), "UI", "found mid-lane", "--reported-by", "claude", "--no-fetch"]) == 1
    out, err = capsys.readouterr()
    assert "created" not in out and not list((wt / "docs" / "backlog").glob("UI/*.md"))
    assert "refused: this is a lane worktree" in err and "LANES-63" in err
    assert "Add --push" in err and "--in-lane mints here anyway" in err


def test_in_lane_mints_into_the_worktree_and_says_the_number_is_unreserved(tmp_path, monkeypatch, capsys):
    repo, wt = _lane_repo(tmp_path, monkeypatch)
    assert bn.main(["--root", str(wt), "UI", "rides in the commit", "--reported-by", "claude",
                    "--no-fetch", "--in-lane"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith("created docs/backlog/UI/UI-1-rides-in-the-commit.md")
    assert (wt / "docs/backlog/UI/UI-1-rides-in-the-commit.md").exists()
    assert not (repo / "docs/backlog/UI").exists()
    assert "in-lane mint" in err and "LANES-63" in err


def test_push_from_a_lane_worktree_mints_into_the_main_clone_and_reserves_the_id_on_origin(tmp_path, monkeypatch, capsys):
    """LANES-63: --push from a worktree targets the main clone the worktree shares refs with,
    pushes the one file under the OK-free guard, and the worktree never gets the file."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    repo, wt = _lane_repo(tmp_path, monkeypatch)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "-u", "origin", "HEAD:refs/heads/main")
    _git(repo, "branch", "-q", "-M", "main")
    (repo / "docs/backlog/INFRA/INFRA-1-thing.md").unlink()      # the stub has no frontmatter; --check must pass
    _git(repo, "commit", "-qam", "drop the stub")
    _git(repo, "push", "-q", "origin", "main")
    assert bn.main(["--root", str(wt), "UI", "reserved on origin", "--reported-by", "claude", "--push"]) == 0
    out, err = capsys.readouterr()
    assert "minting into the main clone" in err and "LANES-63" in err
    assert out.startswith("created docs/backlog/UI/UI-1-reserved-on-origin.md")
    assert (repo / "docs/backlog/UI/UI-1-reserved-on-origin.md").exists()
    assert not (wt / "docs/backlog/UI").exists()
    _git(repo, "fetch", "-q", "origin")
    on_origin = _git(repo, "ls-tree", "-r", "--name-only", "origin/main").stdout
    assert "docs/backlog/UI/UI-1-reserved-on-origin.md" in on_origin


def test_push_is_refused_when_the_main_clone_is_off_the_main_branch(tmp_path, monkeypatch, capsys):
    repo, wt = _lane_repo(tmp_path, monkeypatch)
    _git(repo, "checkout", "-q", "-b", "elsewhere")
    with pytest.raises(SystemExit):
        bn.main(["--root", str(wt), "UI", "x", "--reported-by", "claude", "--push", "--no-fetch"])
    assert "must be on `main`" in capsys.readouterr().err
    assert not (repo / "docs/backlog/UI").exists() and not (wt / "docs/backlog/UI").exists()


def test_context_replaces_the_stub_so_one_push_carries_a_complete_issue(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _point_at(monkeypatch, repo)
    path = bn.create_issue("UI", "with context", reported_by="claude", regen_index=False, fetch=False,
                           context="The problem, where it shows, the fix suggested.\n")
    text = path.read_text(encoding="utf-8")
    assert "## Context\n\nThe problem, where it shows, the fix suggested.\n\n## Acceptance criteria" in text
    assert bn.CONTEXT_STUB not in text
    plain = bn.create_issue("UI", "without", reported_by="claude", regen_index=False, fetch=False)
    assert bn.CONTEXT_STUB in plain.read_text(encoding="utf-8") and bn.BODY_STUB.startswith("## Context\n\n(What this is")


def test_the_new_command_pushes_from_the_main_clone_even_inside_a_lane():
    """LANES-63: /lanes:new used to skip the push inside a worktree; the issue then took a
    number another lane could land first."""
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "commands" / "new.md").read_text(encoding="utf-8")
    assert "--reported-by=me [--context" in text and "--push" in text and "LANES-63" in text
    assert "skip this: the issue rides in the lane" not in text
