"""lanes_claim.py: a slice is claimed in one pushed commit, or not at all (LANES-9)."""
import datetime

import pytest

import lanes_claim as lcl
import lanes_doctor as ld
from conftest import git

NOW = datetime.datetime(2026, 10, 7, 9, 5)


def _issue(issue_id, status="open"):
    project = issue_id.rsplit("-", 1)[0]
    current = ("⏳ IN-PROGRESS (2026-10-07 08:00, Other's session, worktree w, branch b) — **ACTIVE LANE.** x"
               if status == "in-progress" else "Open.")
    return (f"---\nid: {issue_id}\nproject: {project}\ntype: story\nstatus: {status}\npriority: normal\n"
            f"blocked_on: null\nassignee: tester\nreported_by: claude\nopened: 2026-10-01\nclosed: null\n"
            f"commit: null\nresolution: null\nlinks: []\n---\n\n# {issue_id} — thing\n\n## Context\n\nx\n\n"
            f"## Current status\n\n{current}\n\n## Resolution\n\n(fill on close)\n")


def _commit_issues(clone, issues, msg="docs(backlog): seed"):
    paths = []
    for issue_id, status in issues:
        project = issue_id.rsplit("-", 1)[0]
        d = clone / "docs" / "backlog" / project
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{issue_id}-thing.md"
        p.write_text(_issue(issue_id, status), encoding="utf-8")
        paths.append(str(p.relative_to(clone)))
    git("add", *paths, cwd=clone)
    git("commit", "-q", "-m", msg, cwd=clone)


def _clone(origin, path, tmp_path, name="Tester"):
    git("clone", "-q", str(origin), str(path), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=path)
    git("config", "user.name", name, cwd=path)
    return path


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A bare origin with CORE-1..4 open (CORE-5 claimed, CORE-6 closed) and the main clone."""
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    seed = _clone(origin, tmp_path / "seed", tmp_path)
    (seed / "README.md").write_text("# p\n", encoding="utf-8")
    git("add", "README.md", cwd=seed)
    git("commit", "-q", "-m", "init", cwd=seed)
    _commit_issues(seed, [("CORE-1", "open"), ("CORE-2", "blocked"), ("CORE-3", "open"),
                          ("CORE-4", "open"), ("CORE-5", "in-progress"), ("CORE-6", "closed")])
    git("push", "-q", "origin", "main", cwd=seed)
    clone = _clone(origin, tmp_path / "proj", tmp_path)
    monkeypatch.chdir(clone)
    monkeypatch.setattr(lcl, "_now", lambda: NOW)
    return origin, clone, seed


def _origin_text(origin, tmp_path, issue_id):
    return git("--git-dir", str(origin), "show", f"main:docs/backlog/CORE/{issue_id}-thing.md", cwd=tmp_path)


def _origin_log(origin, tmp_path, n=1):
    return git("--git-dir", str(origin), "log", f"-{n}", "--format=%s", "main", cwd=tmp_path)


def _marker(text):
    return next(l for l in text.splitlines() if l.startswith("⏳ IN-PROGRESS"))


def test_claims_the_whole_slice_in_one_pushed_commit(setup, tmp_path, capsys):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-2", "CORE-3", "--files", "api/x.py"]) == 0
    assert _origin_log(origin, tmp_path) == "docs(backlog): claim CORE-1 (WORKTREE PENDING), reserve CORE-2, CORE-3"
    first, second, third = (_origin_text(origin, tmp_path, i) for i in ("CORE-1", "CORE-2", "CORE-3"))
    for text in (first, second, third):
        assert "\nstatus: in-progress\n" in text
        m = _marker(text)
        assert ld.MARKER_RE.search(m).groups() == ("2026-10-07", "09:05")
    assert ld.KIND_RE.search(_marker(first)).group(1) == "WORKTREE PENDING"
    assert "Expected files: api/x.py." in _marker(first)
    assert ld.KIND_RE.search(_marker(second)).group(1) == "RESERVED, NOT STARTED"
    assert "queued behind CORE-1" in _marker(second) and "Prior status: `blocked`" in _marker(second)
    assert "queued behind CORE-2" in _marker(third)
    assert "Claimed as part of the 2026-10-07 lane," in _marker(second)    # LANES-57: a lane, not a slice
    assert "Tester's session on " in _marker(first)
    assert "## Current status\n\n⏳" in first and "\n\nOpen.\n" in first     # prior text kept below
    assert git("status", "--porcelain", cwd=clone) == ""


def test_an_id_with_no_file_on_main_refuses_the_whole_slice_and_names_where_it_is(setup, tmp_path, capsys):
    origin, clone, seed = setup
    git("checkout", "-q", "-b", "canary/x", cwd=seed)
    _commit_issues(seed, [("CORE-9", "open")], msg="canary files CORE-9")
    git("push", "-q", "origin", "canary/x", cwd=seed)
    git("fetch", "-q", "origin", cwd=clone)
    before = _origin_log(origin, tmp_path)
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-9"]) == lcl.NOT_CLAIMED
    err = capsys.readouterr().err
    assert "CORE-9: no file on origin/main" in err and "origin/canary/x" in err
    assert _origin_log(origin, tmp_path) == before
    assert "status: open" in (clone / "docs/backlog/CORE/CORE-1-thing.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("taken,why", [("CORE-5", "already claimed"), ("CORE-6", "is `closed`")])
def test_a_claimed_or_closed_id_refuses_the_whole_slice(setup, tmp_path, capsys, taken, why):
    origin, clone, _ = setup
    before = (clone / "docs/backlog/CORE/CORE-5-thing.md").read_bytes()
    assert lcl.main(["--name", "a lane", "CORE-1", taken]) == lcl.NOT_CLAIMED
    assert why in capsys.readouterr().err
    assert (clone / "docs/backlog/CORE/CORE-5-thing.md").read_bytes() == before   # never touched
    assert git("status", "--porcelain", cwd=clone) == ""


def test_behind_extends_a_claimed_lane(setup, tmp_path):
    origin, clone, _ = setup
    assert lcl.main(["CORE-3", "CORE-4", "--behind", "CORE-5"]) == 0
    assert _origin_log(origin, tmp_path) == "docs(backlog): reserve CORE-3, CORE-4 behind CORE-5"
    assert "queued behind CORE-5" in _marker(_origin_text(origin, tmp_path, "CORE-3"))
    assert "queued behind CORE-3" in _marker(_origin_text(origin, tmp_path, "CORE-4"))
    assert "RESERVED, NOT STARTED" in _marker(_origin_text(origin, tmp_path, "CORE-3"))


def test_behind_an_unclaimed_issue_is_refused(setup, capsys):
    assert lcl.main(["CORE-3", "--behind", "CORE-4"]) == lcl.NOT_CLAIMED
    assert "not a claimed lane" in capsys.readouterr().err


def test_a_rejected_push_rebases_and_lands(setup, tmp_path, monkeypatch):
    """Another session pushed an unrelated commit after this one fetched."""
    origin, clone, seed = setup
    real_sync = lcl.Claim.sync

    def sync_then_race(self):
        real_sync(self)
        (seed / "notes.md").write_text("x\n", encoding="utf-8")
        git("add", "notes.md", cwd=seed)
        git("commit", "-q", "-m", "docs: another session", cwd=seed)
        git("push", "-q", "origin", "main", cwd=seed)

    monkeypatch.setattr(lcl.Claim, "sync", sync_then_race)
    assert lcl.main(["--name", "a lane", "CORE-1"]) == 0
    assert _origin_log(origin, tmp_path, 2).splitlines() == [
        "docs(backlog): claim CORE-1 (WORKTREE PENDING)", "docs: another session"]


def test_a_concurrent_claim_of_the_same_id_withdraws_this_one(setup, tmp_path, monkeypatch, capsys):
    origin, clone, seed = setup
    real_sync = lcl.Claim.sync

    def sync_then_rival(self):
        real_sync(self)
        p = seed / "docs/backlog/CORE/CORE-1-thing.md"
        p.write_text(p.read_text(encoding="utf-8").replace("status: open", "status: in-progress")
                     .replace("Open.", "⏳ rival claim"), encoding="utf-8")
        git("commit", "-q", "-am", "docs(backlog): rival claims CORE-1", cwd=seed)
        git("push", "-q", "origin", "main", cwd=seed)

    monkeypatch.setattr(lcl.Claim, "sync", sync_then_rival)
    assert lcl.main(["--name", "a lane", "CORE-1"]) == lcl.NOT_CLAIMED
    assert "withdrawn" in capsys.readouterr().err
    assert _origin_log(origin, tmp_path) == "docs(backlog): rival claims CORE-1"
    assert git("rev-parse", "HEAD", cwd=clone) == git("rev-parse", "origin/main", cwd=clone)
    assert git("status", "--porcelain", cwd=clone) == ""


def test_refused_in_a_lane_worktree_and_off_main(setup, tmp_path, monkeypatch, capsys):
    origin, clone, _ = setup
    wt = tmp_path / "proj-lane"
    git("worktree", "add", "-q", str(wt), "-b", "lane", cwd=clone)
    monkeypatch.chdir(wt)
    assert lcl.main(["--name", "a lane", "CORE-1"]) == lcl.NOT_CLAIMED
    assert "lane worktree" in capsys.readouterr().err
    monkeypatch.chdir(clone)
    git("checkout", "-q", "-b", "side", cwd=clone)
    assert lcl.main(["--name", "a lane", "CORE-1"]) == lcl.NOT_CLAIMED
    assert "not `main`" in capsys.readouterr().err


def test_a_diverged_main_clone_is_refused(setup, tmp_path, capsys):
    """Another session's unpushed commit on local main while origin moved (LANES-23's shape)."""
    origin, clone, seed = setup
    (clone / "local.md").write_text("x\n", encoding="utf-8")
    git("add", "local.md", cwd=clone)
    git("commit", "-q", "-m", "local", cwd=clone)
    (seed / "other.md").write_text("y\n", encoding="utf-8")
    git("add", "other.md", cwd=seed)
    git("commit", "-q", "-m", "other", cwd=seed)
    git("push", "-q", "origin", "main", cwd=seed)
    assert lcl.main(["--name", "a lane", "CORE-1"]) == lcl.NOT_CLAIMED
    assert "diverged" in capsys.readouterr().err


def test_non_main_direct_work_on_local_main_keeps_the_claim_local(setup, tmp_path, capsys):
    origin, clone, _ = setup
    (clone / "app.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "app.py", cwd=clone)
    git("commit", "-q", "-m", "code on main", cwd=clone)
    before = _origin_log(origin, tmp_path)
    assert lcl.main(["--name", "a lane", "CORE-1"]) == lcl.NOT_PUSHED
    assert _origin_log(origin, tmp_path) == before
    assert "app.py" in capsys.readouterr().err


def test_dry_run_writes_nothing(setup, tmp_path, capsys):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-3", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "WORKTREE PENDING" in out and "queued behind CORE-1" in out
    assert git("status", "--porcelain", cwd=clone) == ""


# --- the recorded lane (LANES-10) -------------------------------------------------

def _fm(text, key):
    return next((l.split(":", 1)[1].strip() for l in text.split("\n---\n", 1)[0].splitlines()
                 if l.startswith(f"{key}:")), None)


def test_every_issue_of_a_slice_records_the_same_lane(setup, tmp_path):
    origin, _, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-2", "CORE-3"]) == 0
    lanes = {_fm(_origin_text(origin, tmp_path, i), "lane") for i in ("CORE-1", "CORE-2", "CORE-3")}
    assert lanes == {"CORE-1@2026-10-07"}
    text = _origin_text(origin, tmp_path, "CORE-1")
    assert text.count("\nlane:") == 1 and "status: in-progress\nlane: CORE-1@2026-10-07\n" in text


def test_behind_a_pre_field_claim_derives_the_key_the_view_derives(setup, tmp_path):
    origin, _, _ = setup
    # CORE-5 was claimed (marker 2026-10-07 08:00) before the field existed.
    assert lcl.main(["CORE-3", "--behind", "CORE-5"]) == 0
    assert _fm(_origin_text(origin, tmp_path, "CORE-3"), "lane") == "CORE-5@2026-10-07"


def test_behind_a_recorded_lane_copies_its_value(setup, tmp_path, monkeypatch):
    origin, _, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1"]) == 0
    monkeypatch.setattr(lcl, "_now", lambda: NOW + datetime.timedelta(days=1))
    assert lcl.main(["CORE-3", "--behind", "CORE-1"]) == 0
    assert _fm(_origin_text(origin, tmp_path, "CORE-3"), "lane") == "CORE-1@2026-10-07"


def test_with_claim_replaces_a_stale_lane_line_instead_of_adding_one():
    text = _issue("CORE-1").replace("status: open\n", "status: open\nlane: OLD-1@2026-01-01\n")
    out = lcl.with_claim(text, "⏳ IN-PROGRESS (x) — **WORKTREE PENDING.** y", "CORE-1@2026-10-07")
    assert out.count("\nlane:") == 1 and "lane: CORE-1@2026-10-07" in out


# --- the lane's name (LANES-80) ---------------------------------------------------

def test_a_new_lane_without_a_name_is_refused_and_writes_nothing(setup, tmp_path, capsys):
    origin, clone, _ = setup
    for argv, why in ((["CORE-1", "CORE-2"], "a new lane needs a name"),
                      (["--name", "   ", "CORE-1"], "a new lane needs a name"),
                      (["--name", "[draft]", "CORE-1"], "a lane name is plain words"),
                      (["--name", "", "CORE-1", "--dry-run"], "a new lane needs a name")):
        assert lcl.main(argv) == lcl.NOT_CLAIMED, argv
        err = capsys.readouterr().err
        assert why in err and "Nothing was written." in err, argv
    assert git("status", "--porcelain", cwd=clone) == ""
    assert _origin_log(origin, tmp_path) == "docs(backlog): seed"


def test_the_name_is_written_beside_the_lane_on_every_issue(setup, tmp_path, capsys):
    origin, _, _ = setup
    assert lcl.main(["CORE-1", "CORE-2", "--name", "  Export   to PDF "]) == 0
    assert "lane CORE-1@2026-10-07: Export to PDF" in capsys.readouterr().out
    for i in ("CORE-1", "CORE-2"):
        text = _origin_text(origin, tmp_path, i)
        assert "\nlane: CORE-1@2026-10-07\nlane_name: Export to PDF\n" in text, i
        assert text.count("\nlane_name:") == 1, i


def test_behind_and_next_in_join_under_the_lanes_name(setup, tmp_path):
    origin, _, _ = setup
    assert lcl.main(["CORE-1", "CORE-2", "--name", "Export to PDF"]) == 0
    assert lcl.main(["CORE-3", "--behind", "CORE-2"]) == 0
    assert lcl.main(["CORE-4", "--next-in", "CORE-1"]) == 0
    for i in ("CORE-3", "CORE-4"):
        assert _fm(_origin_text(origin, tmp_path, i), "lane_name") == "Export to PDF", i


def test_a_lane_from_before_the_name_gains_none(setup, tmp_path):
    origin, _, _ = setup
    assert lcl.main(["CORE-3", "--behind", "CORE-5"]) == 0    # CORE-5 predates both fields
    assert "lane_name:" not in _origin_text(origin, tmp_path, "CORE-3")


@pytest.mark.parametrize("argv", [["CORE-3", "--behind", "CORE-5", "--name", "x"],
                                  ["CORE-3", "--next-in", "CORE-5", "--name", "x"],
                                  ["--resume", "CORE-5", "--name", "x"]])
def test_name_only_names_a_new_lane(setup, argv):
    with pytest.raises(SystemExit):
        lcl.main(argv)


def test_with_lane_replaces_the_name_with_the_key():
    text = _issue("CORE-1").replace("status: open\n", "status: open\nlane: OLD-1@2026-01-01\nlane_name: Old\n")
    out = lcl.with_lane(text, "CORE-2@2026-10-07", "New")
    assert "status: open\nlane: CORE-2@2026-10-07\nlane_name: New\n" in out
    assert out.count("\nlane_name:") == 1
    assert "lane_name:" not in lcl.with_lane(text, "CORE-2@2026-10-07")


def test_an_epic_is_never_claimed(setup, tmp_path, capsys):
    """LANES-31: claim the children; the epic reads in progress through them."""
    origin, clone, _ = setup
    p = clone / "docs/backlog/CORE/CORE-7-thing.md"
    p.write_text(_issue("CORE-7").replace("type: story", "type: epic"), encoding="utf-8")
    git("add", str(p.relative_to(clone)), cwd=clone)
    git("commit", "-q", "-m", "docs(backlog): an epic", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-7"]) == lcl.NOT_CLAIMED
    assert "CORE-7: is an epic" in capsys.readouterr().err
    assert "status: open" in (clone / "docs/backlog/CORE/CORE-1-thing.md").read_text(encoding="utf-8")


# --- --next-in: an issue at the FRONT of a lane (LANES-49) ----------------------

import backlog_index as bidx   # noqa: E402  (the view's grouping is what "next" must mean)


def _view_order(clone, monkeypatch, key):
    for k, v in bidx.settings(clone).items():
        monkeypatch.setattr(bidx, k, v)
    issues, _ = bidx.load_issues()
    lane = next(ln for ln in bidx.lanes_in_flight(issues) if ln["key"] == key)
    return [m["id"] for m in lane["members"]]


def _land(clone, issue_id):
    """The lead lands: closed, done, marker gone, `lane:` kept (what the backfill leaves)."""
    rel = f"docs/backlog/CORE/{issue_id}-thing.md"
    text = (clone / rel).read_text(encoding="utf-8")
    text = text.replace("status: in-progress", "status: closed").replace("resolution: null", "resolution: done")
    text = "\n".join(l for l in text.split("\n") if not l.startswith("⏳ IN-PROGRESS"))
    (clone / rel).write_text(text, encoding="utf-8")
    git("add", rel, cwd=clone)
    git("commit", "-q", "-m", f"docs(backlog): close {issue_id}", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)


def test_next_in_puts_an_issue_ahead_of_the_reserved_ones(setup, tmp_path, monkeypatch, capsys):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-2", "CORE-3"]) == 0
    assert lcl.main(["CORE-4", "--next-in", "CORE-1"]) == 0
    assert _origin_log(origin, tmp_path) == "docs(backlog): CORE-4 next in lane CORE-1@2026-10-07"
    new = _origin_text(origin, tmp_path, "CORE-4")
    assert _fm(new, "status") == "in-progress" and _fm(new, "lane") == "CORE-1@2026-10-07"
    assert "RESERVED, NOT STARTED" in _marker(new) and "queued behind CORE-1." in _marker(new)
    assert "queued behind CORE-4." in _marker(_origin_text(origin, tmp_path, "CORE-2"))
    assert "queued behind CORE-2." in _marker(_origin_text(origin, tmp_path, "CORE-3"))
    assert _view_order(clone, monkeypatch, "CORE-1@2026-10-07") == ["CORE-1", "CORE-4", "CORE-2", "CORE-3"]
    assert "re-queued CORE-2 behind CORE-4" in capsys.readouterr().out


def test_next_in_after_the_lead_landed_takes_the_lane_key(setup, tmp_path, monkeypatch):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-2", "CORE-3"]) == 0
    _land(clone, "CORE-1")
    assert lcl.main(["CORE-4", "--next-in", "CORE-1@2026-10-07"]) == 0
    assert "queued behind CORE-1." in _marker(_origin_text(origin, tmp_path, "CORE-4"))
    assert "queued behind CORE-4." in _marker(_origin_text(origin, tmp_path, "CORE-2"))
    assert _view_order(clone, monkeypatch, "CORE-1@2026-10-07") == ["CORE-1", "CORE-4", "CORE-2", "CORE-3"]


def test_next_in_moves_a_lane_opened_by_mistake(setup, tmp_path, monkeypatch):
    """The INFRA-122 shape: between two issues of a slice, a mid-slice issue was claimed
    bare and opened a lane of its own. --next-in moves it in, PENDING kept, ahead of the
    reservation, and its stray lane is gone from the view."""
    origin, clone, _ = setup
    assert lcl.main(["--name", "Export to PDF", "CORE-1", "CORE-2"]) == 0
    _land(clone, "CORE-1")
    assert lcl.main(["--name", "a stray lane", "CORE-3"]) == 0
    assert _fm(_origin_text(origin, tmp_path, "CORE-3"), "lane") == "CORE-3@2026-10-07"
    assert lcl.main(["CORE-3", "--next-in", "CORE-2"]) == 0
    moved = _origin_text(origin, tmp_path, "CORE-3")
    assert _fm(moved, "lane") == "CORE-1@2026-10-07" and moved.count("\nlane:") == 1
    # LANES-80: it takes the lane's name -- from the landed lead -- in place of its own
    assert _fm(moved, "lane_name") == "Export to PDF" and moved.count("\nlane_name:") == 1
    assert "WORKTREE PENDING" in _marker(moved)
    assert "queued behind CORE-3." in _marker(_origin_text(origin, tmp_path, "CORE-2"))
    assert _origin_log(origin, tmp_path) == "docs(backlog): CORE-3 next in lane CORE-1@2026-10-07 (moved: CORE-3)"
    assert _view_order(clone, monkeypatch, "CORE-1@2026-10-07") == ["CORE-1", "CORE-3", "CORE-2"]
    issues, _ = bidx.load_issues()
    assert [ln["key"] for ln in bidx.lanes_in_flight(issues)] == ["CORE-5@2026-10-07", "CORE-1@2026-10-07"]


def test_next_in_refusals_write_nothing(setup, tmp_path, capsys):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-2"]) == 0
    assert lcl.main(["--name", "a lane", "CORE-3", "CORE-4"]) == 0
    before = _origin_log(origin, tmp_path)
    cases = [
        (["CORE-4", "--next-in", "CORE-5"], "claimed by other"),            # another session's lane
        (["CORE-5", "--next-in", "CORE-1"], "already claimed by another session"),
        (["CORE-2", "--next-in", "CORE-1"], "already in lane CORE-1@2026-10-07"),
        (["CORE-4", "--next-in", "CORE-9@2026-01-01"], "no lane in flight"),
        (["CORE-6", "--next-in", "CORE-1"], "is `closed`"),
        (["CORE-4", "--next-in", "CORE-1"], "also holds CORE-3"),           # half a lane
        (["CORE-3", "CORE-4", "--next-in", "CORE-1"], "already works CORE-1"),   # two heads
    ]
    for argv, why in cases:
        assert lcl.main(argv) == lcl.NOT_CLAIMED, argv
        assert why in capsys.readouterr().err, argv
    assert _origin_log(origin, tmp_path) == before
    assert git("status", "--porcelain", cwd=clone) == ""


def test_next_in_dry_run_writes_nothing(setup, tmp_path, capsys):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-2"]) == 0
    before = _origin_log(origin, tmp_path)
    assert lcl.main(["CORE-4", "--next-in", "CORE-1", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "queued behind CORE-1." in out and "queued behind CORE-4." in out and "would commit:" in out
    assert _origin_log(origin, tmp_path) == before and git("status", "--porcelain", cwd=clone) == ""


def test_next_in_takes_no_behind_or_files(setup):
    for extra in (["--behind", "CORE-1"], ["--files", "x"]):
        with pytest.raises(SystemExit):
            lcl.main(["CORE-4", "--next-in", "CORE-1", *extra])


def test_with_lane_and_requeued_each_change_one_line():
    text = _issue("CORE-1", "in-progress").replace(
        "**ACTIVE LANE.** x", "**RESERVED, NOT STARTED.** Claimed as part of the 2026-10-07 slice, "
        "queued behind CORE-9. No worktree yet and no files touched.")
    laned = lcl.with_lane(text, "CORE-2@2026-10-07")
    assert "status: in-progress\nlane: CORE-2@2026-10-07\n" in laned and laned.count("\nlane:") == 1
    assert lcl.with_lane(laned, "CORE-3@2026-10-07").count("\nlane:") == 1
    out = lcl.requeued(laned, "CORE-4")
    assert "queued behind CORE-4." in out and "CORE-9" not in out
    assert sum(a != b for a, b in zip(laned.split("\n"), out.split("\n"))) == 1


# --- --release: this machine's own claim, undone in one push (LANES-81) -------------------

def _clone_text(clone, issue_id):
    return (clone / f"docs/backlog/CORE/{issue_id}-thing.md").read_text(encoding="utf-8")


def _activate(clone, issue_id, worktree, branch):
    """Flip this machine's PENDING marker to ACTIVE the way worktree-increment step 2 does."""
    import re
    p = clone / f"docs/backlog/CORE/{issue_id}-thing.md"
    text = re.sub(r"\) — \*\*WORKTREE PENDING\.\*\* Claim pushed; worktree not yet created\.",
                  f", worktree {worktree}, branch {branch}) — **ACTIVE LANE.**", p.read_text(encoding="utf-8"))
    p.write_text(text, encoding="utf-8")
    git("commit", "-q", "-am", f"docs(backlog): {issue_id} claim → ACTIVE LANE", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)


def test_release_returns_a_reservation_to_its_prior_status_and_keeps_the_chain(setup, tmp_path, capsys):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-2", "CORE-3"]) == 0
    capsys.readouterr()
    assert lcl.main(["--release", "CORE-2", "--reason", "claimed, not reached"]) == 0
    out = capsys.readouterr().out
    assert "released CORE-2: reserved → blocked" in out and "re-queued CORE-3 behind CORE-1" in out
    assert _origin_log(origin, tmp_path) == "docs(backlog): release CORE-2 — claimed, not reached"
    text = _origin_text(origin, tmp_path, "CORE-2")
    assert "\nstatus: blocked\n" in text                                  # its Prior status, not `open`
    assert "\nlane:" not in text and "\nlane_name:" not in text
    assert "IN-PROGRESS" not in text                                      # --check reads that word as a claim
    assert "## Current status\n\n↩ CLAIM RELEASED (2026-10-07 09:05, Tester's session on " in text
    assert ") — was reserved, not started in lane CORE-1@2026-10-07; nothing of it landed. claimed, not reached." in text
    assert "\n\nOpen.\n" in text                                          # the text under the marker is kept
    third = _origin_text(origin, tmp_path, "CORE-3")
    assert "queued behind CORE-1." in _marker(third) and "\nlane: CORE-1@2026-10-07\n" in third
    assert git("status", "--porcelain", cwd=clone) == ""


def test_release_of_an_active_claim_leaves_its_worktree_and_branch_and_names_them(setup, tmp_path, capsys):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-3"]) == 0
    _activate(clone, "CORE-1", "proj-core-1", "core-1-work")
    capsys.readouterr()
    assert lcl.main(["--release", "CORE-1", "--reason", "too big for one landing; split it"]) == 0
    out = capsys.readouterr().out
    assert "released CORE-1: active → open" in out
    assert "worktree proj-core-1 and branch core-1-work untouched" in out
    assert "CORE-3 heads its lane now" in out
    text = _origin_text(origin, tmp_path, "CORE-1")
    assert "\nstatus: open\n" in text and "IN-PROGRESS" not in text
    assert ("was the lane's active issue (worktree proj-core-1, branch core-1-work) in lane "
            "CORE-1@2026-10-07; nothing of it landed. too big for one landing; split it.") in text
    assert "\nstatus: in-progress\n" in _origin_text(origin, tmp_path, "CORE-3")   # the rest of the lane stays


def test_release_of_a_whole_lane_restores_every_issue(setup, tmp_path, capsys):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-2", "CORE-3"]) == 0
    assert lcl.main(["--release", "CORE-1", "CORE-2", "CORE-3"]) == 0
    assert _origin_log(origin, tmp_path) == ("docs(backlog): release CORE-1, CORE-2, CORE-3 — "
                                             "claim released, nothing landed")
    for issue_id, status in (("CORE-1", "open"), ("CORE-2", "blocked"), ("CORE-3", "open")):
        text = _origin_text(origin, tmp_path, issue_id)
        assert f"\nstatus: {status}\n" in text and "IN-PROGRESS" not in text and "\nlane" not in text
    assert "re-queued" not in capsys.readouterr().out


@pytest.mark.parametrize("argv,why", [
    (["--release", "CORE-5"], "claimed by other, not this machine"),     # another session's claim
    (["--release", "CORE-4"], "CORE-4: not claimed (status `open`)"),
    (["--release", "CORE-6"], "CORE-6: not claimed (status `closed`)"),
    (["--release", "CORE-1", "CORE-4"], "CORE-4: not claimed"),          # all or nothing
    (["--release", "CORE-1", "--reason", "see ⏳ IN-PROGRESS"], "may not quote a claim marker"),
])
def test_release_refuses_and_writes_nothing(setup, tmp_path, capsys, argv, why):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1"]) == 0
    before = {i: _clone_text(clone, i) for i in ("CORE-1", "CORE-4", "CORE-5")}
    head = _origin_log(origin, tmp_path)
    assert lcl.main(argv) == lcl.NOT_CLAIMED
    err = capsys.readouterr().err
    assert "NOT RELEASED" in err and why in err and "Nothing was written." in err
    assert {i: _clone_text(clone, i) for i in before} == before
    assert _origin_log(origin, tmp_path) == head and git("status", "--porcelain", cwd=clone) == ""


def test_release_dry_run_prints_the_lines_and_writes_nothing(setup, tmp_path, capsys):
    origin, clone, _ = setup
    assert lcl.main(["--name", "a lane", "CORE-1", "CORE-2"]) == 0
    head = _origin_log(origin, tmp_path)
    capsys.readouterr()
    assert lcl.main(["--release", "CORE-2", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would release CORE-2: reserved → blocked" in out
    assert "↩ CLAIM RELEASED (2026-10-07 09:05" in out and "would commit: docs(backlog): release CORE-2" in out
    assert _origin_log(origin, tmp_path) == head and git("status", "--porcelain", cwd=clone) == ""


@pytest.mark.parametrize("argv", [
    ["--release", "CORE-1", "--name", "x"],
    ["--release", "CORE-1", "--behind", "CORE-5"],
    ["--release", "CORE-1", "--next-in", "CORE-5"],
    ["--release", "CORE-1", "--files", "x"],
    ["CORE-1", "--name", "x", "--reason", "why"],          # --reason only means something with --release
    ["--release"],
])
def test_release_takes_ids_reason_and_dry_run_only(setup, argv):
    with pytest.raises(SystemExit):
        lcl.main(argv)
