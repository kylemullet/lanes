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
    assert lcl.main(["CORE-1", "CORE-2", "CORE-3", "--files", "api/x.py"]) == 0
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
    assert lcl.main(["CORE-1", "CORE-9"]) == lcl.NOT_CLAIMED
    err = capsys.readouterr().err
    assert "CORE-9: no file on origin/main" in err and "origin/canary/x" in err
    assert _origin_log(origin, tmp_path) == before
    assert "status: open" in (clone / "docs/backlog/CORE/CORE-1-thing.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("taken,why", [("CORE-5", "already claimed"), ("CORE-6", "is `closed`")])
def test_a_claimed_or_closed_id_refuses_the_whole_slice(setup, tmp_path, capsys, taken, why):
    origin, clone, _ = setup
    before = (clone / "docs/backlog/CORE/CORE-5-thing.md").read_bytes()
    assert lcl.main(["CORE-1", taken]) == lcl.NOT_CLAIMED
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
    assert lcl.main(["CORE-1"]) == 0
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
    assert lcl.main(["CORE-1"]) == lcl.NOT_CLAIMED
    assert "withdrawn" in capsys.readouterr().err
    assert _origin_log(origin, tmp_path) == "docs(backlog): rival claims CORE-1"
    assert git("rev-parse", "HEAD", cwd=clone) == git("rev-parse", "origin/main", cwd=clone)
    assert git("status", "--porcelain", cwd=clone) == ""


def test_refused_in_a_lane_worktree_and_off_main(setup, tmp_path, monkeypatch, capsys):
    origin, clone, _ = setup
    wt = tmp_path / "proj-lane"
    git("worktree", "add", "-q", str(wt), "-b", "lane", cwd=clone)
    monkeypatch.chdir(wt)
    assert lcl.main(["CORE-1"]) == lcl.NOT_CLAIMED
    assert "lane worktree" in capsys.readouterr().err
    monkeypatch.chdir(clone)
    git("checkout", "-q", "-b", "side", cwd=clone)
    assert lcl.main(["CORE-1"]) == lcl.NOT_CLAIMED
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
    assert lcl.main(["CORE-1"]) == lcl.NOT_CLAIMED
    assert "diverged" in capsys.readouterr().err


def test_non_main_direct_work_on_local_main_keeps_the_claim_local(setup, tmp_path, capsys):
    origin, clone, _ = setup
    (clone / "app.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "app.py", cwd=clone)
    git("commit", "-q", "-m", "code on main", cwd=clone)
    before = _origin_log(origin, tmp_path)
    assert lcl.main(["CORE-1"]) == lcl.NOT_PUSHED
    assert _origin_log(origin, tmp_path) == before
    assert "app.py" in capsys.readouterr().err


def test_dry_run_writes_nothing(setup, tmp_path, capsys):
    origin, clone, _ = setup
    assert lcl.main(["CORE-1", "CORE-3", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "WORKTREE PENDING" in out and "queued behind CORE-1" in out
    assert git("status", "--porcelain", cwd=clone) == ""


# --- the recorded lane (LANES-10) -------------------------------------------------

def _fm(text, key):
    return next((l.split(":", 1)[1].strip() for l in text.split("\n---\n", 1)[0].splitlines()
                 if l.startswith(f"{key}:")), None)


def test_every_issue_of_a_slice_records_the_same_lane(setup, tmp_path):
    origin, _, _ = setup
    assert lcl.main(["CORE-1", "CORE-2", "CORE-3"]) == 0
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
    assert lcl.main(["CORE-1"]) == 0
    monkeypatch.setattr(lcl, "_now", lambda: NOW + datetime.timedelta(days=1))
    assert lcl.main(["CORE-3", "--behind", "CORE-1"]) == 0
    assert _fm(_origin_text(origin, tmp_path, "CORE-3"), "lane") == "CORE-1@2026-10-07"


def test_with_claim_replaces_a_stale_lane_line_instead_of_adding_one():
    text = _issue("CORE-1").replace("status: open\n", "status: open\nlane: OLD-1@2026-01-01\n")
    out = lcl.with_claim(text, "⏳ IN-PROGRESS (x) — **WORKTREE PENDING.** y", "CORE-1@2026-10-07")
    assert out.count("\nlane:") == 1 and "lane: CORE-1@2026-10-07" in out


def test_an_epic_is_never_claimed(setup, tmp_path, capsys):
    """LANES-31: claim the children; the epic reads in progress through them."""
    origin, clone, _ = setup
    p = clone / "docs/backlog/CORE/CORE-7-thing.md"
    p.write_text(_issue("CORE-7").replace("type: story", "type: epic"), encoding="utf-8")
    git("add", str(p.relative_to(clone)), cwd=clone)
    git("commit", "-q", "-m", "docs(backlog): an epic", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    assert lcl.main(["CORE-1", "CORE-7"]) == lcl.NOT_CLAIMED
    assert "CORE-7: is an epic" in capsys.readouterr().err
    assert "status: open" in (clone / "docs/backlog/CORE/CORE-1-thing.md").read_text(encoding="utf-8")
