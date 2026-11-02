"""backlog_split.py: an issue bigger than one landing becomes an epic with children (LANES-47)."""
import sys

import pytest

import backlog_index as bidx
import backlog_new as bn
import backlog_split as bs
import lanes_config as lc
from conftest import git

MINE = f"⏳ IN-PROGRESS (2026-10-14 01:00, Tester's session on Tester+{sys.platform}@host, worktree w, branch b) — **ACTIVE LANE.** Expected files: x."
THEIRS = "⏳ IN-PROGRESS (2026-10-14 01:00, Other's session on other-box@host, worktree w, branch b) — **ACTIVE LANE.** x."


@pytest.fixture
def backlog(repo, monkeypatch):
    """Solo mode in `repo`: this machine is Tester+<platform>, short `tester`."""
    monkeypatch.setattr(lc, "git_user_name", lambda cwd=None: "Tester")
    for k, v in bidx.settings(repo, {"backlog": {"projects": ["CORE"]}}).items():
        monkeypatch.setattr(bidx, k, v)
    monkeypatch.setattr(bn, "BACKLOG_REL", "docs/backlog")
    return repo


def put(root, iid, status="open", type_="story", extra="", current="Open."):
    d = root / "docs" / "backlog" / "CORE"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{iid}-thing.md"
    p.write_text(f"---\nid: {iid}\nproject: CORE\ntype: {type_}\nstatus: {status}\npriority: high\n"
                 f"blocked_on: null\nassignee: tester\nreported_by: claude\nopened: 2026-10-01\nclosed: null\n"
                 f"commit: null\nresolution: null\nlinks: []\n{extra}---\n\n# {iid} — thing\n\n## Context\n\nx\n\n"
                 f"## Current status\n\n{current}\n\n## Resolution\n\n(Fill on close.)\n", encoding="utf-8")
    return p


def meta(root, iid):
    p = next((root / "docs" / "backlog" / "CORE").glob(f"{iid}-*.md"))
    m, body = bidx.parse_frontmatter(p.read_text(encoding="utf-8"))
    return m, body


def check_is_green():
    issues, problems = bidx.load_issues()
    assert bidx.check_problems(issues, problems) == []


def test_an_open_issue_becomes_the_epic_of_its_children(backlog):
    put(backlog, "CORE-1")
    mode, epic, ids, rels, _ = bs.split("CORE-1", ["parse it", "write it"], "tester", today="2026-10-14")
    assert (mode, epic, ids) == ("convert", "CORE-1", ["CORE-2", "CORE-3"])
    assert rels[0] == "docs/backlog/CORE/CORE-1-thing.md" and len(rels) == 3
    parent, body = meta(backlog, "CORE-1")
    assert parent["type"] == "epic" and parent["status"] == "open"
    status = body.split("## Current status", 1)[1]
    assert status.lstrip().startswith("Split 2026-10-14 into [[CORE-2]], [[CORE-3]]") and "Open." in status
    child, cbody = meta(backlog, "CORE-2")
    assert (child["epic"], child["priority"], child["assignee"], child["reported_by"], child["status"],
            child["opened"]) == ("CORE-1", "high", "tester", "tester", "open", "2026-10-14")
    assert "split from [[CORE-1]]" in cbody and "before its lane started" in cbody
    assert "# CORE-3 — write it" in (backlog / rels[2]).read_text(encoding="utf-8")
    check_is_green()


def test_an_epic_gets_children_and_is_left_alone(backlog):
    p = put(backlog, "CORE-1", type_="epic")
    before = p.read_bytes()
    mode, epic, ids, rels, _ = bs.split("CORE-1", ["one more"], "claude", today="2026-10-14")
    assert (mode, epic, ids) == ("children", "CORE-1", ["CORE-2"]) and rels == ["docs/backlog/CORE/CORE-2-one-more.md"]
    assert p.read_bytes() == before
    check_is_green()


def test_a_claimed_issue_files_its_remainder_under_a_new_epic_over_it(backlog):
    """The partial landing: the claim stays where it is, and the issue closes as the new
    epic's first child. Only its `epic:` line changes."""
    p = put(backlog, "CORE-1", status="in-progress", extra="lane: CORE-1@2026-10-14\n",
            current=MINE + "\n\nWorking.")
    before = p.read_text(encoding="utf-8")
    mode, epic, ids, rels, _ = bs.split("CORE-1", ["the rest", "the tail"], "tester", today="2026-10-14")
    assert (mode, epic, ids) == ("remainder", "CORE-2", ["CORE-3", "CORE-4"])
    wrapper, wbody = meta(backlog, "CORE-2")
    assert wrapper["type"] == "epic" and wrapper["status"] == "open" and wrapper.get("epic") is None
    assert "# CORE-2 — EPIC — thing" in (backlog / rels[1]).read_text(encoding="utf-8")
    assert "[[CORE-3]], [[CORE-4]] carry" in wbody
    after = p.read_text(encoding="utf-8")
    assert [l for l in after.split("\n") if l not in before.split("\n")] == ["epic: CORE-2"]
    assert meta(backlog, "CORE-3")[0]["epic"] == "CORE-2" and "remainder of a partial landing" in meta(backlog, "CORE-3")[1]
    check_is_green()


def test_a_claimed_issue_under_an_epic_files_its_remainder_there(backlog):
    put(backlog, "CORE-9", type_="epic")
    p = put(backlog, "CORE-1", status="in-progress", extra="lane: CORE-1@2026-10-14\nepic: CORE-9\n",
            current=MINE)
    before = p.read_bytes()
    mode, epic, ids, rels, _ = bs.split("CORE-1", ["the rest"], "tester", today="2026-10-14")
    assert (mode, epic, ids) == ("remainder", "CORE-9", ["CORE-10"])
    assert p.read_bytes() == before and len(rels) == 1
    check_is_green()


@pytest.mark.parametrize("status,current,why", [
    ("closed", "Done.", "is `closed`"),
    ("verified", "Landed.", "is `verified`"),
    ("in-progress", THEIRS, "claimed by another session"),
])
def test_refusals_write_nothing(backlog, status, current, why):
    put(backlog, "CORE-1", status=status, current=current)
    before = sorted(p.name for p in (backlog / "docs/backlog/CORE").iterdir())
    with pytest.raises(bs.Refused, match=why.replace("`", ".")):
        bs.split("CORE-1", ["x"], "tester")
    assert sorted(p.name for p in (backlog / "docs/backlog/CORE").iterdir()) == before


def test_an_unknown_id_and_an_epic_child_are_refused(backlog):
    put(backlog, "CORE-1")
    with pytest.raises(bs.Refused, match="no issue file"):
        bs.split("CORE-7", ["x"], "tester")
    with pytest.raises(bs.Refused, match="not epics"):
        bs.split("CORE-1", ["x"], "tester", type_="epic")


def test_a_failure_part_way_restores_the_issue_and_removes_the_children(backlog, monkeypatch):
    p = put(backlog, "CORE-1")
    before = p.read_bytes()
    real, calls = bn.create_issue, []

    def flaky(*a, **kw):
        calls.append(a)
        if len(calls) == 2:
            raise ValueError("disk full")
        return real(*a, **kw)

    monkeypatch.setattr(bn, "create_issue", flaky)
    with pytest.raises(ValueError):
        bs.split("CORE-1", ["one", "two"], "tester")
    assert p.read_bytes() == before
    assert [x.name for x in (backlog / "docs/backlog/CORE").iterdir()] == ["CORE-1-thing.md"]


def test_dry_run_names_the_ids_and_writes_nothing(backlog, capsys):
    p = put(backlog, "CORE-1", status="in-progress", current=MINE)
    before = p.read_bytes()
    assert bs.main(["CORE-1", "the rest", "--reported-by", "claude", "--dry-run", "--no-fetch"]) == 0
    out = capsys.readouterr().out
    assert "would file the remainder of CORE-1 under CORE-2" in out
    assert "would mint CORE-3 — the rest (epic: CORE-2)" in out
    assert p.read_bytes() == before and len(list((backlog / "docs/backlog/CORE").iterdir())) == 1


def test_push_commits_every_file_and_pushes_from_the_main_clone(tmp_path, monkeypatch, capsys):
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    clone = tmp_path / "proj"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=clone)
    git("config", "user.name", "Tester", cwd=clone)
    put(clone, "CORE-1")
    git("add", "docs", cwd=clone)
    git("commit", "-q", "-m", "seed", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    monkeypatch.chdir(clone)
    monkeypatch.setattr(lc, "git_user_name", lambda cwd=None: "Tester")
    for k, v in bidx.settings(clone, {}).items():
        monkeypatch.setattr(bidx, k, v)
    monkeypatch.setattr(bn, "BACKLOG_REL", "docs/backlog")
    assert bs.main(["CORE-1", "one", "two", "--reported-by", "claude", "--push"]) == 0
    log = git("--git-dir", str(origin), "log", "-1", "--format=%s", "main", cwd=tmp_path)
    assert log == "docs(backlog): split CORE-1 into CORE-2, CORE-3"
    files = git("--git-dir", str(origin), "ls-tree", "-r", "--name-only", "main", cwd=tmp_path).splitlines()
    assert {"docs/backlog/CORE/CORE-2-one.md", "docs/backlog/CORE/CORE-3-two.md"} <= set(files)
    assert "committed and" in capsys.readouterr().out


def test_push_off_the_main_clone_is_refused_before_anything_is_written(backlog, monkeypatch):
    p = put(backlog, "CORE-1")
    before = p.read_bytes()
    monkeypatch.setattr(bs.push_guard, "position", lambda root, main: "this is a lane worktree")
    with pytest.raises(SystemExit):
        bs.main(["CORE-1", "one", "--reported-by", "claude", "--push"])
    assert p.read_bytes() == before and len(list((backlog / "docs/backlog/CORE").iterdir())) == 1


def test_a_child_carries_the_acceptance_criteria_stub(backlog):
    """LANES-60: a split child is an issue like any other, so it gets the table too."""
    put(backlog, "CORE-1")
    bs.split("CORE-1", ["parse it"], "tester", today="2026-10-14")
    _, cbody = meta(backlog, "CORE-2")
    assert [l for l in cbody.splitlines() if l.startswith("## ")] == [
        "## Context", "## Acceptance criteria", "## Current status", "## Resolution"]
    assert bn.ACCEPTANCE_STUB in cbody
    check_is_green()


# --- a lane's split mints its children on the main branch, with --push (LANES-76) ----------

def _lane(tmp_path, monkeypatch, parent_status="in-progress", parent_current=MINE):
    """A bare origin, a main clone with one issue (claimed by this machine by default) pushed to
    origin, and a lane worktree off main. Solo mode, this machine is Tester."""
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    clone = tmp_path / "proj"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=clone)
    git("config", "user.name", "Tester", cwd=clone)
    (clone / ".claude" / "lanes").mkdir(parents=True)
    (clone / ".claude" / "lanes" / "config.toml").write_text('[backlog]\nprojects = ["CORE"]\n', encoding="utf-8")
    put(clone, "CORE-1", status=parent_status, current=parent_current)
    git("add", "-A", cwd=clone)
    git("commit", "-q", "-m", "seed", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    wt = tmp_path / "proj-lane"
    git("worktree", "add", "-q", str(wt), "-b", "lane-work", cwd=clone)
    monkeypatch.setattr(lc, "git_user_name", lambda cwd=None: "Tester")
    monkeypatch.setattr(bidx, "regenerate", lambda: None)
    monkeypatch.setattr(bidx, "refresh_main_view", lambda: None)
    return origin, clone, wt


def test_a_split_in_a_lane_worktree_without_push_is_refused_and_names_the_fix(tmp_path, monkeypatch, capsys):
    """LANES-76: children minted in a worktree are on no ref until the lane lands, so another
    lane can take their numbers first — the LANES-63 exposure on the split path."""
    origin, clone, wt = _lane(tmp_path, monkeypatch)
    before = (wt / "docs/backlog/CORE/CORE-1-thing.md").read_bytes()
    assert bs.main(["--root", str(wt), "CORE-1", "the rest", "--reported-by", "claude", "--no-fetch"]) == 1
    out, err = capsys.readouterr()
    assert "wrote" not in out and "mint" not in out
    assert "refused: this is a lane worktree" in err and "LANES-76" in err
    assert "Add --push" in err and "--in-lane splits here anyway" in err
    assert (wt / "docs/backlog/CORE/CORE-1-thing.md").read_bytes() == before
    assert len(list((wt / "docs/backlog/CORE").iterdir())) == 1
    assert len(list((clone / "docs/backlog/CORE").iterdir())) == 1


def test_in_lane_splits_in_the_worktree_and_says_the_numbers_are_unreserved(tmp_path, monkeypatch, capsys):
    origin, clone, wt = _lane(tmp_path, monkeypatch)
    assert bs.main(["--root", str(wt), "CORE-1", "the rest", "--reported-by", "claude", "--no-fetch",
                    "--in-lane"]) == 0
    out, err = capsys.readouterr()
    assert "in-lane split" in err and "LANES-76" in err
    assert "wrote docs/backlog/CORE/CORE-2-epic-thing.md" in out and "wrote docs/backlog/CORE/CORE-3-the-rest.md" in out
    assert {p.name for p in (wt / "docs/backlog/CORE").iterdir()} == {"CORE-1-thing.md", "CORE-2-epic-thing.md", "CORE-3-the-rest.md"}
    assert len(list((clone / "docs/backlog/CORE").iterdir())) == 1          # the main clone saw nothing


def test_push_from_a_lane_mints_the_children_into_the_main_clone_and_the_parents_edit_stays_in_the_lane(tmp_path, monkeypatch, capsys):
    """LANES-76: the epic and the child are minted in the main clone and pushed, so their IDs are
    on origin at once; the claimed parent's `epic:` line is written to the LANE's copy, which the
    lane's resolving commit carries. The main clone's copy of the claim is untouched."""
    origin, clone, wt = _lane(tmp_path, monkeypatch)
    parent_main = clone / "docs/backlog/CORE/CORE-1-thing.md"
    parent_lane = wt / "docs/backlog/CORE/CORE-1-thing.md"
    main_before = parent_main.read_bytes()
    assert bs.main(["--root", str(wt), "CORE-1", "the rest", "--reported-by", "claude", "--push"]) == 0
    out, err = capsys.readouterr()
    assert "minting the children into the main clone" in err and "LANES-76" in err
    assert "file the remainder of CORE-1 under CORE-2" in out
    assert "wrote docs/backlog/CORE/CORE-2-epic-thing.md" in out and "wrote docs/backlog/CORE/CORE-3-the-rest.md" in out
    assert f"wrote docs/backlog/CORE/CORE-1-thing.md in the lane {wt}" in out and "committed and" in out
    # the main clone: children minted and pushed, the claim byte-for-byte as it was
    assert parent_main.read_bytes() == main_before
    assert {p.name for p in (clone / "docs/backlog/CORE").iterdir()} == {"CORE-1-thing.md", "CORE-2-epic-thing.md", "CORE-3-the-rest.md"}
    log = git("--git-dir", str(origin), "log", "-1", "--format=%s", "main", cwd=tmp_path)
    assert log == "docs(backlog): file the remainder of CORE-1 as CORE-3"
    files = git("--git-dir", str(origin), "ls-tree", "-r", "--name-only", "main", cwd=tmp_path).splitlines()
    assert {"docs/backlog/CORE/CORE-2-epic-thing.md", "docs/backlog/CORE/CORE-3-the-rest.md"} <= set(files)
    assert "docs/backlog/CORE/CORE-1-thing.md" in files
    assert git("--git-dir", str(origin), "show", "main:docs/backlog/CORE/CORE-1-thing.md", cwd=tmp_path).encode() + b"\n" == main_before
    # the lane: the parent carries `epic: CORE-2`, uncommitted, and no child file
    meta, _ = bidx.parse_frontmatter(parent_lane.read_text(encoding="utf-8"))
    assert meta["epic"] == "CORE-2" and meta["status"] == "in-progress"
    assert {p.name for p in (wt / "docs/backlog/CORE").iterdir()} == {"CORE-1-thing.md"}
    assert git("status", "--porcelain", cwd=wt).strip() == "M docs/backlog/CORE/CORE-1-thing.md"


def test_push_from_a_lane_converts_an_unclaimed_issue_in_the_main_clone(tmp_path, monkeypatch, capsys):
    """An open issue that is not this lane's claim has no copy the lane owns: the whole split,
    parent conversion included, happens in the main clone and is pushed."""
    origin, clone, wt = _lane(tmp_path, monkeypatch, parent_status="open", parent_current="Open.")
    assert bs.main(["--root", str(wt), "CORE-1", "one", "two", "--reported-by", "claude", "--push"]) == 0
    out, _ = capsys.readouterr()
    assert "convert CORE-1 to an epic" in out and "in the lane" not in out
    meta, _ = bidx.parse_frontmatter((clone / "docs/backlog/CORE/CORE-1-thing.md").read_text(encoding="utf-8"))
    assert meta["type"] == "epic"
    assert git("status", "--porcelain", cwd=wt).strip() == ""
    log = git("--git-dir", str(origin), "log", "-1", "--format=%s", "main", cwd=tmp_path)
    assert log == "docs(backlog): split CORE-1 into CORE-2, CORE-3"
