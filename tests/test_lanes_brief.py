"""lanes_brief.py: the startup Brief, rendered by a script (LANES-67).

The incident: the session wrote the Brief from prose at every startup, so it drifted between
sessions, put the one line that must be read last, cited bare IDs, and spent 7 of its 14 lines
on one project saying nothing had changed. The script prints one fixed order from the backlog
and the checks' status lines; the session's judgment goes in as arguments, and only there.
"""
import datetime
import io
import random
import sys
from pathlib import Path

import pytest

import backlog_index as bidx
import lanes_brief as lb
import lanes_config as lc
from conftest import git

TODAY = datetime.date(2026, 10, 28)


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    raw = {"backlog": {"projects": ["UI", "PIPE", "LANES", "BD"]},
           "git": {"permanent_branches": ["reference-impl", "canary/*"]},
           "operators": [{"name": "Tester", "platform": sys.platform, "id": "test-box", "short": "kyle",
                          "certifies": True, "may_edit_code": True}]}
    monkeypatch.setattr(lc, "git_user_name", lambda cwd=None: "Tester")
    for k, v in bidx.settings(tmp_path, raw).items():
        monkeypatch.setattr(bidx, k, v)


def _ago(days):
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def _issue(iid, **kw):
    proj = iid.split("-")[0]
    base = {"id": iid, "project": proj, "type": "story", "status": "open", "priority": "normal",
            "assignee": "kyle", "opened": _ago(3), "closed": None, "links": [],
            "_path": Path(f"docs/backlog/{proj}/{iid}-x.md"), "_title": f"Title of {iid} — and the rest of it"}
    base.update(kw)
    return base


def _active(iid, branch, machine="test-box@Host"):
    return _issue(iid, status="in-progress", lane=f"{iid}@2026-10-28",
                  _marker={"state": "active", "claimed": "2026-10-28 00:49", "machine": machine,
                           "who": "Kyle", "worktree": f"wt-{iid}", "branch": branch, "behind": None})


def _quiet():
    return [_active("UI-1", "ui-1-work"), _issue("BD-2", due="2026-10-30"), _issue("PIPE-3", opened=_ago(40)),
            _issue("BD-4", due="2026-12-01")]


def test_a_quiet_day_is_a_handful_of_lines_critical_first_and_the_stat_last():
    out = lb.render(_quiet(), ["OK pull: up to date at abc1234", "OK doctor: 0 warn, 0 fail",
                               "CUE patent triage: 3 records awaiting triage"], who="kyle", today=TODAY)
    assert out == [
        "critical: none",
        "CUE patent triage: 3 records awaiting triage",
        "due: BD-2 Title of BD-2 10-30 (in 2d)",                      # BD-4 is past the seven days
        "lanes: 1 — UI-1 Title of UI-1",
        "health: 2 ok — pull · doctor",
        "4 live · 0 critical · oldest 40d",
    ]


def test_the_critical_line_carries_critical_checks_then_judgment_and_never_the_priority_field():
    issues = _quiet() + [_issue("PIPE-5", priority="critical", opened=_ago(90))]
    out = lb.render(issues, ["OK pull: up to date", "CRITICAL nightly: RED 2026-10-27 at c634eb8",
                             "[canary] an unmarked line"],
                    who="kyle", today=TODAY, critical=["🔒 UI-1: verified, awaiting the landing OK"],
                    notes=["UI-1 and PIPE-3 both expect to edit app.css"], branches=["auth-28-work"],
                    landed=["PIPE-3", "UI-9"])
    assert out[0] == "critical: 2 — nightly: RED 2026-10-27 at c634eb8 · 🔒 UI-1: verified, awaiting the landing OK"
    assert "PIPE-5" not in out[0], "a top-priority issue that has waited 90 days is not news"
    assert out[1] == "[canary] an unmarked line"                  # shown in full, never folded away
    rest = out[2:]
    assert [l.split(":", 1)[0] for l in rest] == ["due", "lanes", "⚠️ UI-1 and PIPE-3 both expect to edit app.css",
                                                  "branches", "landed", "health", "5 live · 1 critical · oldest 90d"]
    assert "landed: PIPE-3 Title of PIPE-3 · UI-9" in rest           # an ID with no file stays bare
    assert "health: 1 ok — pull" in rest


def test_every_id_carries_its_title_cut_to_its_first_clause():
    assert lb.short_title("Mid-Century theme — teak, mustard and teal") == "Mid-Century theme"
    long = "A" * 60
    assert lb.short_title(long) == "A" * (lb.TITLE_WIDTH - 1) + "…" and len(lb.short_title(long)) == lb.TITLE_WIDTH
    assert lb.short_title("") == ""


def test_a_lane_names_its_phase_and_a_machine_other_than_this_one():
    pending = _issue("LANES-7", status="in-progress", lane="LANES-7@2026-10-28",
                     _marker={"state": "pending", "claimed": "2026-10-28 00:49", "machine": "test-box@H",
                              "who": "Kyle", "worktree": None, "branch": None, "behind": None})
    elsewhere = _active("UI-8", "ui-8-work", machine="kyle-win@Zephyr")
    line = next(l for l in lb.render([pending, elsewhere], [], who="kyle", today=TODAY) if l.startswith("lanes:"))
    assert line == "lanes: 2 — LANES-7 Title of LANES-7 (worktree pending) · UI-8 Title of UI-8 on kyle-win"


def test_the_same_state_renders_the_same_text_whatever_the_input_order():
    issues = _quiet() + [_active("PIPE-6", "pipe-6-work"), _issue("BD-7", due="2026-10-27")]
    status = ["OK pull: up to date", "CUE slow machine: 1.9x", "OK doctor: 0 warn"]
    first = lb.render(issues, status, who="kyle", today=TODAY)
    for seed in range(5):
        shuffled = issues[:]
        random.Random(seed).shuffle(shuffled)
        assert lb.render(shuffled, status, who="kyle", today=TODAY) == first
    assert "BD-7 Title of BD-7 10-27 (1d OVERDUE)" in next(l for l in first if l.startswith("due:"))


def _origin_and_clone(tmp_path):
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    clone = tmp_path / "clone"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=clone)
    git("config", "user.name", "Tester", cwd=clone)
    (clone / "a.txt").write_text("a\n", encoding="utf-8")
    git("add", "a.txt", cwd=clone)
    git("commit", "-q", "-m", "init", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    return clone


def _branch_with_a_commit(clone, name):
    git("checkout", "-q", "-b", name, "main", cwd=clone)
    (clone / f"{name.replace('/', '_')}.txt").write_text(name, encoding="utf-8")
    git("add", "-A", cwd=clone)
    git("commit", "-q", "-m", f"work on {name}", cwd=clone)
    git("push", "-q", "origin", name, cwd=clone)
    git("checkout", "-q", "main", cwd=clone)


def test_unlanded_branches_skip_the_main_branch_a_claimed_one_and_the_permanent_patterns(tmp_path, monkeypatch):
    clone = _origin_and_clone(tmp_path)
    for name in ("ui-1-work", "reference-impl", "canary/kyle-mac", "auth-28-work"):
        _branch_with_a_commit(clone, name)
    git("checkout", "-q", "-b", "landed-work", "main", cwd=clone)     # merged: not unlanded
    git("push", "-q", "origin", "landed-work", cwd=clone)
    git("checkout", "-q", "main", cwd=clone)
    git("fetch", "-q", "origin", cwd=clone)
    monkeypatch.setattr(bidx, "ROOT", clone)
    assert lb.unlanded_branches([_active("UI-1", "ui-1-work")]) == ["auth-28-work"]
    monkeypatch.setattr(bidx, "PERMANENT_BRANCHES", ())
    assert lb.unlanded_branches([]) == ["auth-28-work", "canary/kyle-mac", "reference-impl", "ui-1-work"]


def test_landed_ids_are_the_issues_cited_since_the_ref_oldest_first_minus_backlog_bookkeeping(tmp_path, monkeypatch):
    clone = _origin_and_clone(tmp_path)
    base = git("rev-parse", "HEAD", cwd=clone)
    for subject in ("feat(ui): UI-7 — a thing", "docs(backlog): close UI-8 — backfill", "fix: PIPE-3, and UI-7 again"):
        git("commit", "-q", "--allow-empty", "-m", subject, cwd=clone)
    monkeypatch.setattr(bidx, "ROOT", clone)
    assert lb.landed_ids(base) == ["UI-7", "PIPE-3"]
    assert lb.landed_ids("HEAD") == [] and lb.landed_ids("no-such-ref") == [] and lb.landed_ids(None) == []


def test_the_cli_reads_the_status_lines_on_stdin_and_takes_judgment_as_arguments(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("CRITICAL nightly: RED at c634eb8\nOK pull: up to date\n"))
    assert lb.main(["--critical", "a stale claim on UI-1 to release", "--since", "no-such-ref"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "critical: 2 — nightly: RED at c634eb8 · a stale claim on UI-1 to release",
        "health: 1 ok — pull",
        "0 live · 0 critical",
    ]


# --- since the last Brief (LANES-68) ---------------------------------------------------------

NOW = datetime.datetime(2026, 10, 28, 9, 30)
STATUS = ["OK pull: up to date", "OK canary: last run GREEN at abc1234", "CUE patent triage: 3 awaiting triage"]


def _last(issues, status=STATUS, branches=("auth-28-work",)):
    return lb.snapshot(issues, status, branches=branches, tip="abc", now=NOW - datetime.timedelta(hours=2))


def test_a_second_brief_on_the_same_state_says_nothing_changed():
    issues = _quiet()
    out = lb.render(issues, STATUS, who="kyle", today=TODAY, now=NOW, branches=["auth-28-work"], last=_last(issues))
    assert out == [
        "critical: none",
        "since 07:30: nothing changed",
        "due: BD-2 Title of BD-2 10-30 (in 2d)",
        "lanes: 1 in flight, unchanged",
        "health: 2 ok, 1 cue unchanged (patent triage) — pull · canary",
        "4 live · 0 critical · oldest 40d",
    ]


def test_the_since_line_names_what_landed_opened_and_closed_and_which_lanes_started_or_ended():
    before = _quiet() + [_active("PIPE-6", "pipe-6-work"), _issue("BD-8")]
    last = _last(before)
    after = [i for i in _quiet() if i["id"] != "UI-1"] + [
        _issue("UI-1", status="verified", lane="UI-1@2026-10-28"),       # landed, so not "closed" again
        _issue("BD-8", status="closed", resolution="wont-do"),           # closed without a landing
        _active("PIPE-6", "pipe-6-work"), _active("LANES-9", "lanes-9-work"), _issue("UI-10")]
    out = lb.render(after, STATUS, who="kyle", today=TODAY, now=NOW, landed=["UI-1"], last=last)
    since = next(l for l in out if l.startswith("since "))
    assert since == ("since 07:30: landed UI-1 Title of UI-1; opened UI-10 Title of UI-10; closed BD-8 Title of BD-8; "
                     "lanes started LANES-9 Title of LANES-9; lanes ended UI-1 Title of UI-1")
    assert next(l for l in out if l.startswith("lanes:")).startswith("lanes: 2 — ")   # the set changed: in full
    assert not any(l.startswith("landed:") for l in out), "the since line carries the landings"
    assert not any(l.startswith("branches:") for l in out), "an unchanged set of branches is not news"


def test_a_check_whose_level_moved_gets_its_own_line_even_when_it_is_now_ok():
    issues = _quiet()
    last = _last(issues, status=["OK pull: up to date", "CUE slow machine: 1.9x", "CUE patent triage: 3",
                                 "CRITICAL nightly: RED"])
    now = ["OK pull: up to date", "OK slow machine: timings normal", "CUE patent triage: 3",
           "OK nightly: GREEN at c634eb8", "CUE toggle clocks: a review in 13d"]
    out = lb.render(issues, now, who="kyle", today=TODAY, now=NOW, last=last)
    assert out[0] == "critical: none"
    assert out[1:4] == ["CUE toggle clocks: a review in 13d",                  # new: shown
                        "OK slow machine: timings normal (was CUE)",          # moved: shown once
                        "OK nightly: GREEN at c634eb8 (was CRITICAL)"]
    assert "health: 3 ok, 1 cue unchanged (patent triage) — pull · slow machine · nightly" in out


def test_a_since_label_from_another_day_names_the_day():
    issues = _quiet()
    last = lb.snapshot(issues, STATUS, tip="abc", now=datetime.datetime(2026, 10, 26, 17, 8))
    assert "since 10-26 17:08: nothing changed" in lb.render(issues, STATUS, who="kyle", today=TODAY, now=NOW, last=last)


def test_the_saved_brief_lives_in_the_clone_git_dir_shared_by_worktrees_and_never_tracked(tmp_path, monkeypatch, capsys):
    clone = _origin_and_clone(tmp_path)
    monkeypatch.setattr(bidx, "ROOT", clone)
    path = lb.state_path()
    assert path == clone / ".git" / "lanes" / "last-brief.json"
    monkeypatch.setattr(sys, "stdin", io.StringIO("OK pull: up to date\nCUE patent triage: 3\n"))
    assert lb.main([]) == 0
    assert "since" not in capsys.readouterr().out, "no saved Brief: the whole Brief"
    assert path.is_file() and git("status", "--porcelain", cwd=clone) == ""
    git("commit", "-q", "--allow-empty", "-m", "feat(ui): UI-7 — a landing", cwd=clone)
    monkeypatch.setattr(sys, "stdin", io.StringIO("OK pull: up to date\nCUE patent triage: 3\n"))
    lb.main([])
    out = capsys.readouterr().out.splitlines()
    assert out[1].startswith("since ") and out[1].endswith(": landed UI-7"), "--since defaults to the saved tip"
    worktree = tmp_path / "wt"
    git("worktree", "add", "-q", str(worktree), "-b", "topic", cwd=clone)
    monkeypatch.setattr(bidx, "ROOT", worktree)
    assert lb.state_path().resolve() == path.resolve(), "every worktree of the clone reads the same Brief"


def test_full_ignores_the_saved_brief_and_no_save_leaves_it(tmp_path, monkeypatch, capsys):
    clone = _origin_and_clone(tmp_path)
    monkeypatch.setattr(bidx, "ROOT", clone)
    for argv in ([], ["--full"]):
        monkeypatch.setattr(sys, "stdin", io.StringIO("OK pull: up to date\n"))
        lb.main(argv)
        assert not any(l.startswith("since ") for l in capsys.readouterr().out.splitlines()), argv
    saved = lb.state_path().read_text(encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO("OK pull: up to date\nOK doctor: 0 warn\n"))
    lb.main(["--no-save"])
    assert lb.state_path().read_text(encoding="utf-8") == saved
    lb.state_path().write_text("not json", encoding="utf-8")
    assert lb.load_state(lb.state_path()) is None, "an unreadable saved Brief means the whole Brief"
