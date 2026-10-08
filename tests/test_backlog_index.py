"""The backlog integrity gate and views, ported from the project that built them.

Every test runs against a throwaway tree: the autouse fixture resolves solo-mode
settings under tmp_path and assigns them onto the module, so nothing here can touch
a real backlog, and tests that need git build a real repository (the properties
under test are git ones).
"""
import subprocess
import sys
from pathlib import Path

import pytest

import backlog_index as bidx
import backlog_new as bnew
import lanes_config as lc
from conftest import git


@pytest.fixture(autouse=True)
def _solo_settings_under_tmp(tmp_path, monkeypatch):
    """Point EVERY module global at tmp, solo mode, default vocab plus the test
    projects/operators the fixtures use. A test that wants a repo re-points ROOT."""
    raw = {"backlog": {"projects": ["UI", "PIPE", "INFRA", "PROD", "BD", "X", "P", "A"]},
           "operators": [
               {"name": "Tester", "platform": sys.platform, "id": "test-box", "short": "kyle",
                "certifies": True, "may_edit_code": True},
               {"name": "Other", "platform": "win32", "id": "other-box", "short": "mike",
                "certifies": False, "may_edit_code": False}]}
    values = bidx.settings(tmp_path / "guard", raw)
    monkeypatch.setattr(lc, "git_user_name", lambda cwd=None: "Tester")
    values = bidx.settings(tmp_path / "guard", raw)   # re-resolve with the patched user
    for k, v in values.items():
        monkeypatch.setattr(bidx, k, v)
    monkeypatch.setattr(bnew, "ROOT", bidx.ROOT)
    monkeypatch.setattr(bnew, "BACKLOG", bidx.BACKLOG)
    monkeypatch.setattr(bnew, "BACKLOG_REL", bidx.BACKLOG_REL)


# --- configuration becomes module globals ---------------------------------

def test_settings_resolve_config_into_flat_globals(tmp_path):
    raw = {"backlog": {"dir": "work/issues", "projects": ["APP"], "claim_marker_exempt": ["APP-1"],
                       "resolution_required_from": "2026-01-01", "view_port": 9001},
           "git": {"main_branch": "trunk", "main_direct_paths": ["docs/", "notes/", "*.md"]}}
    v = bidx.settings(tmp_path, raw)
    assert v["BACKLOG"] == tmp_path / "work" / "issues" and v["BACKLOG_REL"] == "work/issues"
    assert v["INDEX"].name == "INDEX.md" and v["HTML_VIEW"].parent == v["BACKLOG"]
    assert v["PROJECTS"] == ("APP",) and v["CLAIM_MARKER_EXEMPT"] == {"APP-1"}
    assert v["RESOLUTION_CUTOVER"] == "2026-01-01" and v["VIEW_PORT"] == 9001
    assert v["MAIN_BRANCH"] == "trunk"
    assert v["DOCS_LANE_PREFIXES"] == ("docs/", "notes/", "*.md")   # defaults to main_direct_paths
    assert v["REPO_NAME"] == tmp_path.name


def test_solo_defaults_certify_and_derive_the_assignee(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "git_user_name", lambda cwd=None: "Ada Lovelace")
    v = bidx.settings(tmp_path, {})
    assert v["SOLO"] and v["MACHINE"]["certifies"] and v["CERTIFIER_LABEL"] == "your"
    assert v["ASSIGNEES"] == ("ada-lovelace", "shared") and v["REPORTERS"] == ("claude", "ada-lovelace")
    assert v["DEFAULT_ASSIGNEE"] == "ada-lovelace"
    assert v["RESOLUTION_CUTOVER"] is None and v["CLAIM_MARKER_EXEMPT"] == set()


def test_two_operator_settings_name_the_certifier_and_default_assignee():
    assert bidx.SOLO is False and bidx.MACHINE["id"] == "test-box" and bidx.certifies()
    assert bidx.CERTIFIER_LABEL == "kyle's" and bidx.DEFAULT_ASSIGNEE == "kyle"
    assert bidx.ASSIGNEES == ("kyle", "mike", "shared") and bidx.REPORTERS == ("claude", "kyle", "mike")


def test_protocol_vocabularies_are_constants_not_config():
    assert bidx.STATUSES == ("in-progress", "open", "blocked", "paused", "verified", "closed")
    assert bidx.LIVE_STATUSES == ("in-progress", "open", "blocked", "paused")
    assert bidx.RESOLUTIONS == ("done", "duplicate", "superseded", "wont-do")
    assert "epic" in bidx.TYPES


# --- the checkers themselves --------------------------------------------

def test_orphaned_commit_citations_flags_a_hash_not_on_head():
    issues = [
        {"id": "UI-12", "_path": "docs/backlog/UI/UI-12-x.md", "commit": "cdc29e0"},
        {"id": "UI-13", "_path": "docs/backlog/UI/UI-13-y.md", "commit": "5d17435"},
    ]
    reachable = {"5d17435" + "a" * 33}
    out = bidx.orphaned_commit_citations(issues, reachable)
    assert len(out) == 1 and "UI-12" in out[0] and "cdc29e0" in out[0]


def test_orphaned_commit_citations_accepts_short_and_full_hashes():
    full = "5d17435" + "a" * 33
    issues = [
        {"id": "A-1", "_path": "a", "commit": "5d17435"},
        {"id": "A-2", "_path": "b", "commit": full},
        {"id": "A-3", "_path": "c", "commit": "5D17435"},
    ]
    assert bidx.orphaned_commit_citations(issues, {full}) == []


def test_orphaned_commit_citations_ignores_null_commits():
    issues = [{"id": "A-1", "_path": "a", "commit": None}, {"id": "A-2", "_path": "b"}]
    assert bidx.orphaned_commit_citations(issues, set()) == []


def test_orphaned_commit_citations_flags_a_non_hash_value():
    issues = [{"id": "A-1", "_path": "a", "commit": "fix(scripts): mint against all refs"}]
    out = bidx.orphaned_commit_citations(issues, set())
    assert len(out) == 1 and "not a git hash" in out[0]


def test_orphaned_commit_citations_skips_when_git_cannot_answer(monkeypatch):
    monkeypatch.setattr(bidx, "reachable_commits", lambda: None)
    issues = [{"id": "A-1", "_path": "a", "commit": "cdc29e0"}]
    assert bidx.orphaned_commit_citations(issues) == []


def test_reachable_commits_head_subjects_and_commit_paths_read_the_repo(repo, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", repo)
    head = git("rev-parse", "HEAD", cwd=repo)
    assert head in bidx.reachable_commits()
    subjects = bidx.head_subjects()
    assert subjects["init"][0] == head
    assert bidx.commit_paths(head) == {"README.md"}


def test_orphaned_claims_flags_each_half_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    (tmp_path / "claimed-no-marker.md").write_text("# X\n\nOpen.\n", encoding="utf-8")
    (tmp_path / "marker-no-claim.md").write_text("# Y\n\n⏳ IN-PROGRESS (...)\n", encoding="utf-8")
    (tmp_path / "agree.md").write_text("# Z\n\n⏳ IN-PROGRESS (...)\n", encoding="utf-8")
    issues = [
        {"id": "P-1", "_path": "claimed-no-marker.md", "status": "in-progress"},
        {"id": "P-2", "_path": "marker-no-claim.md", "status": "open"},
        {"id": "P-3", "_path": "agree.md", "status": "in-progress"},
    ]
    out = bidx.orphaned_claims(issues)
    assert len(out) == 2
    assert any("claimed-no-marker" in o and "absent" in o for o in out)
    assert any("marker-no-claim" in o and "present" in o for o in out)


def test_orphaned_claims_honours_the_configured_exemption(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    (tmp_path / "a1.md").write_text("quotes its own ⏳ IN-PROGRESS marker\n", encoding="utf-8")
    issues = [{"id": "P-1", "_path": "a1.md", "status": "closed"}]
    assert len(bidx.orphaned_claims(issues)) == 1
    monkeypatch.setattr(bidx, "CLAIM_MARKER_EXEMPT", {"P-1"})
    assert bidx.orphaned_claims(issues) == []


def test_regenerate_writes_the_local_index(tmp_path, monkeypatch):
    index = tmp_path / "sub" / "INDEX.md"
    monkeypatch.setattr(bidx, "INDEX", index)
    monkeypatch.setattr(bidx, "HTML_VIEW", tmp_path / "sub" / "index.html")
    monkeypatch.setattr(bidx, "load_issues", lambda: ([], []))
    bidx.regenerate()
    text = index.read_text(encoding="utf-8")
    assert "0 live" in text and "gitignored" in text


def test_check_problems_is_the_union(monkeypatch):
    monkeypatch.setattr(bidx, "orphaned_claims", lambda issues: ["claim-problem"])
    monkeypatch.setattr(bidx, "orphaned_commit_citations", lambda issues: ["cite-problem"])
    monkeypatch.setattr(bidx, "unresolvable_verified", lambda issues: ["verified-problem"])
    monkeypatch.setattr(bidx, "undocumented_verified", lambda issues: ["docs-problem"])
    monkeypatch.setattr(bidx, "dangling_epics", lambda issues: ["epic-problem"])
    monkeypatch.setattr(bidx, "resolution_problems", lambda issues: ["resolution-problem"])
    assert bidx.check_problems([], ["structural"]) == [
        "structural", "claim-problem", "cite-problem", "verified-problem", "docs-problem",
        "epic-problem", "resolution-problem"]


# --- load_issues against a tree -------------------------------------------

FM = ("---\nid: {iid}\nproject: {proj}\ntype: {type_}\nstatus: {status}\npriority: normal\n"
      "blocked_on: null\nassignee: kyle\nreported_by: claude\nopened: 2026-09-27\nclosed: {closed}\n"
      "commit: null\nresolution: {resolution}\nlinks: []\n{extra}---\n\n# {iid} — {title}\n\n"
      "## Context\n\nx\n\n## Current status\n\n{status_body}\n\n## Resolution\n\n{resolution_body}\n")


def put(root, iid, type_="chore", status="open", title="a thing", closed="null", resolution="null",
        extra="", status_body="Open.", resolution_body="(Fill on close: what settled it, with evidence / links.)",
        backlog_rel="docs/backlog", filename=None):
    proj = iid.split("-")[0]
    d = root / backlog_rel / proj
    d.mkdir(parents=True, exist_ok=True)
    p = d / (filename or f"{iid}-{title.replace(' ', '-')}.md")
    p.write_text(FM.format(iid=iid, proj=proj, type_=type_, status=status, closed=closed, resolution=resolution,
                           extra=extra, title=title, status_body=status_body, resolution_body=resolution_body),
                 encoding="utf-8")
    return p


def test_load_issues_reads_the_configured_dir_and_flags_structure(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    monkeypatch.setattr(bidx, "BACKLOG", tmp_path / "work" / "issues")
    monkeypatch.setattr(bidx, "BACKLOG_REL", "work/issues")
    put(tmp_path, "UI-1", backlog_rel="work/issues")
    put(tmp_path, "UI-2", backlog_rel="work/issues", filename="UI-3-wrong-name.md")
    put(tmp_path, "ZZ-1", backlog_rel="work/issues")
    (tmp_path / "work/issues/UI/bad.md").write_text("no frontmatter\n", encoding="utf-8")
    issues, problems = bidx.load_issues()
    ids = sorted(i["id"] for i in issues)
    assert ids == ["UI-1", "UI-2"]
    assert all("epic" in it and "reported_by" in it and "resolution" in it for it in issues)
    assert any("filename doesn't start with its id" in p for p in problems)
    assert any("'ZZ' is not a project" in p for p in problems)
    assert any("missing or unparseable frontmatter" in p for p in problems)
    assert issues[0]["_title"] == "a thing"
    assert "_review" not in issues[0]


def test_load_issues_rejects_out_of_vocabulary_values(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    monkeypatch.setattr(bidx, "BACKLOG", tmp_path / "docs" / "backlog")
    p = put(tmp_path, "UI-1")
    p.write_text(p.read_text(encoding="utf-8").replace("assignee: kyle", "assignee: bob")
                 .replace("reported_by: claude", "reported_by: eve").replace("type: chore", "type: wish"),
                 encoding="utf-8")
    _, problems = bidx.load_issues()
    assert any("assignee='bob'" in x for x in problems)
    assert any("reported_by='eve'" in x for x in problems)
    assert any("type='wish'" in x for x in problems)
    # a legacy `owner:` key is simply unknown now — no shim, no special message
    p.write_text(p.read_text(encoding="utf-8").replace("assignee: bob", "owner: kyle"), encoding="utf-8")
    issues, problems = bidx.load_issues()
    assert issues[0]["assignee"] is None and not any("legacy" in x for x in problems)


# --- the browsable HTML view ---------------------------------------------

def _issue(iid, **kw):
    proj = iid.split("-")[0]
    base = {"id": iid, "project": proj, "type": "chore", "status": "open",
            "priority": "normal", "assignee": "kyle", "opened": "2026-08-01",
            "closed": None, "commit": None, "links": [],
            "_path": Path(f"docs/backlog/{proj}/{iid}-x.md"),
            "_title": f"title for {iid}"}
    base.update(kw)
    return base


def test_render_html_is_self_contained_and_named_after_the_repo(monkeypatch):
    monkeypatch.setattr(bidx, "REPO_NAME", "my-proj")
    page = bidx.render_html([_issue("UI-1"), _issue("PIPE-2", status="closed", closed="2026-08-09")])
    assert page.startswith("<!doctype html>")
    assert "<script src" not in page and "<link" not in page
    assert "http://" not in page and "https://" not in page
    assert "<style>" in page and "applyFilter" in page
    assert "<title>Backlog — my-proj</title>" in page


def test_render_html_rows_carry_every_filter_and_sort_key():
    page = bidx.render_html([_issue("INFRA-3", priority="critical", status="blocked",
                                    assignee="mike", blocked_on="fixtures")])
    for attr in ('data-project="INFRA"', 'data-status="blocked"', 'data-priority="critical"',
                 'data-assignee="mike"', 'data-type="chore"', 'data-priority-rank="0"',
                 'data-status-rank="2"', 'data-age=', 'data-haystack='):
        assert attr in page, f"row is missing {attr}"
    assert 'data-key="priorityRank"' in page and 'data-key="statusRank"' in page


def test_render_html_lists_every_issue_once_with_links_relative_to_the_backlog_dir(monkeypatch):
    monkeypatch.setattr(bidx, "BACKLOG_REL", "work/issues")
    issues = [_issue("UI-1", _path=Path("work/issues/UI/UI-1-x.md")),
              _issue("UI-2", _path=Path("work/issues/UI/UI-2-x.md")),
              _issue("PIPE-9", status="closed", closed="2026-08-01", _path=Path("work/issues/PIPE/PIPE-9-x.md"))]
    page = bidx.render_html(issues)
    for i in issues:
        assert page.count(f">{i['id']}</a>") == 1, f"{i['id']} not rendered exactly once"
    assert 'href="UI/UI-1-x.md"' in page
    assert "<b>2</b> live" in page and "<b>1</b> closed" in page


def test_render_html_escapes_issue_text():
    page = bidx.render_html([_issue("UI-4", _title='<img src=x onerror=alert(1)> & "quoted"',
                                    blocked_on="<b>nope</b>")])
    assert "<img src=x" not in page and "<b>nope</b>" not in page
    assert "&lt;img src=x" in page and "&amp;" in page


def test_html_sort_id_zero_pads_the_numeric_half():
    assert bidx._sort_id({"id": "INFRA-9"}) < bidx._sort_id({"id": "INFRA-14"})
    assert bidx._sort_id({"id": "no-number"}) == "no-number"


def test_html_default_order_is_priority_then_status_then_oldest():
    old_low = _issue("UI-1", priority="low", opened="2026-01-01")
    new_crit = _issue("UI-2", priority="critical", opened="2026-08-30")
    open_norm = _issue("UI-3", priority="normal", status="open", opened="2026-08-01")
    blocked_norm = _issue("UI-4", priority="normal", status="blocked", opened="2026-08-01")
    older_norm = _issue("UI-5", priority="normal", status="open", opened="2026-02-01")
    for i in (old_low, new_crit, open_norm, blocked_norm, older_norm):
        i["_age"] = bidx._age(i["opened"])
    ordered = [i["id"] for i in sorted(
        [old_low, new_crit, open_norm, blocked_norm, older_norm], key=bidx.html_sort_key)]
    assert ordered[0] == "UI-2"
    assert ordered.index("UI-5") < ordered.index("UI-3")
    assert ordered.index("UI-3") < ordered.index("UI-4")
    assert ordered[-1] == "UI-1"


def test_regenerate_writes_both_views(tmp_path, monkeypatch):
    index, view = tmp_path / "INDEX.md", tmp_path / "index.html"
    monkeypatch.setattr(bidx, "INDEX", index)
    monkeypatch.setattr(bidx, "HTML_VIEW", view)
    monkeypatch.setattr(bidx, "load_issues", lambda: ([_issue("UI-1")], []))
    bidx.regenerate()
    assert "UI-1" in index.read_text(encoding="utf-8")
    page = view.read_text(encoding="utf-8")
    assert "UI-1" in page and "gitignored" in page


def test_each_facet_row_has_a_select_all_toggle():
    page = bidx.render_html([_issue("UI-1"), _issue("PIPE-2", assignee="mike", priority="high")])
    for field in ("project", "status", "priority", "assignee"):
        assert f'<fieldset data-field="{field}">' in page
        assert f'class="allbtn" data-all="{field}"' in page, f"{field} row has no select-all"


# --- the In progress section: lanes read from the claim markers (LANES-22) ---

ACTIVE_MK = ("⏳ IN-PROGRESS (2026-10-07 02:40, Kyle's session on kyle-mac@Air, worktree "
             "lanes-lanes-20, branch lanes-20-work) — **ACTIVE LANE.** Expected files: `x`.")
PENDING_MK = "⏳ IN-PROGRESS (2026-10-07 02:45, Kyle's session on kyle-mac@Air) — **WORKTREE PENDING.** Claim pushed."


def _reserved(behind, ts="2026-10-07 02:40"):
    return (f"⏳ IN-PROGRESS ({ts}, Kyle's session on kyle-mac@Air) — "
            f"**RESERVED, NOT STARTED — queued behind {behind}.**")


def _claimed(iid, marker, **kw):
    return _issue(iid, status="in-progress", _marker=bidx.parse_marker(marker), **kw)


def test_parse_marker_reads_every_field_the_skills_write():
    mk = bidx.parse_marker("## Current status\n\n" + ACTIVE_MK)
    assert mk == {"state": "active", "claimed": "2026-10-07 02:40", "who": "Kyle",
                  "machine": "kyle-mac@Air", "worktree": "lanes-lanes-20",
                  "branch": "lanes-20-work", "behind": None}
    assert bidx.parse_marker(PENDING_MK)["state"] == "pending"
    res = bidx.parse_marker(_reserved("LANES-20"))
    assert res["state"] == "reserved" and res["behind"] == "LANES-20" and res["worktree"] is None
    # The older long form and a wiki-linked ID both name the lane they sit behind.
    old = ("⏳ IN-PROGRESS (2026-09-20 10:00, Kyle's session) — **RESERVED, NOT STARTED.** "
           "Claimed as part of the 2026-09-20 slice, queued behind [[CORE-64]]. No worktree yet.")
    assert bidx.parse_marker(old)["behind"] == "CORE-64"
    capital = ("⏳ IN-PROGRESS (2026-10-07 02:53, Kyle's session) — **RESERVED, NOT STARTED.** "
               "Queued behind INFRA-100 (same file, same gate).")
    assert bidx.parse_marker(capital)["behind"] == "INFRA-100"
    assert bidx.parse_marker("no marker here") is None


def test_load_issues_parses_the_marker_only_on_claimed_issues(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    monkeypatch.setattr(bidx, "BACKLOG", tmp_path / "docs" / "backlog")
    put(tmp_path, "UI-1", status="in-progress", status_body=ACTIVE_MK)
    put(tmp_path, "UI-2")
    issues = {i["id"]: i for i in bidx.load_issues()[0]}
    assert issues["UI-1"]["_marker"]["worktree"] == "lanes-lanes-20"
    assert "_marker" not in issues["UI-2"]


def test_lanes_group_a_slice_in_order_and_keep_strays_as_their_own_lane():
    issues = [_claimed("LANES-9", _reserved("LANES-21")),
              _claimed("LANES-20", ACTIVE_MK),
              _claimed("LANES-21", _reserved("LANES-20")),
              _claimed("LANES-22", PENDING_MK),
              # queued behind an issue that already landed: stands alone, never dropped
              _claimed("INFRA-5", _reserved("INFRA-4", ts="2026-10-07 01:00")),
              _claimed("UI-3", "no readable marker"),
              _issue("INFRA-4", status="verified")]
    lanes = bidx.lanes_in_flight(issues)
    ids = [[m["id"] for m in ln["members"]] for ln in lanes]
    assert ["LANES-20", "LANES-21", "LANES-9"] in ids
    assert ["LANES-22"] in ids and ["INFRA-5"] in ids and ["UI-3"] in ids
    assert sum(len(x) for x in ids) == 6
    # oldest claim first; an unreadable claim time sorts last
    assert ids[0] == ["INFRA-5"] and ids[-1] == ["UI-3"]


def test_lanes_survive_a_queued_behind_cycle():
    a = _claimed("X-1", _reserved("X-2"))
    b = _claimed("X-2", _reserved("X-1"))
    lanes = bidx.lanes_in_flight([a, b])
    assert sorted(m["id"] for ln in lanes for m in ln["members"]) == ["X-1", "X-2"]


def test_render_html_shows_lanes_on_top_and_each_claim_once():
    issues = [_claimed("LANES-20", ACTIVE_MK, priority="high"),
              _claimed("LANES-21", _reserved("LANES-20")),
              _issue("UI-1", blocked_on="a long reason"),
              _issue("UI-2", status="closed", closed="2026-09-01")]
    page = bidx.render_html(issues)
    assert page.index("In progress") < page.index("Open queue")
    assert "lanes-lanes-20" in page and "lanes-20-work" in page and "kyle-mac@Air" in page
    assert '<span class="ln">LANES-20/21 <code>lanes-lanes-20</code>' in page
    assert '<time data-ts="2026-10-07 02:40">' in page
    assert page.index(">LANES-20</a>") < page.index(">LANES-21</a>")
    for iid in ("LANES-20", "LANES-21", "UI-1", "UI-2"):
        assert page.count(f">{iid}</a>") == 1, iid
    assert 'class="st st-active"' in page and 'class="st st-reserved"' in page
    # blocked-on rides under the title, full text on hover
    assert '<div class="why" title="a long reason">a long reason</div>' in page
    assert "<b>3</b> live" in page and "<b>2</b> in progress" in page
    assert "no longer claimed" not in page


def test_a_reservation_whose_lead_landed_says_so():
    page = bidx.render_html([_claimed("LANES-9", _reserved("LANES-21")),
                             _issue("LANES-21", status="verified")])
    assert "queued behind LANES-21, no longer claimed" in page


def test_render_html_omits_the_section_with_nothing_in_flight():
    page = bidx.render_html([_issue("UI-1")])
    assert 'class="lanes"' not in page and "<b>0</b> in progress" in page


def test_title_is_the_second_column_everywhere():
    for cols in (bidx.OPEN_COLS, bidx.VERIFIED_COLS, bidx.CLOSED_COLS):
        assert [c[1] for c in cols[:2]] == ["id", "title"]


def test_render_html_lists_problems_in_a_collapsed_callout():
    page = bidx.render_html([_issue("UI-1")], problems=["a.md: <bad>", "b.md: worse"])
    assert '<details class="callout"><summary>⚠️ 2 backlog problems' in page
    assert "<li>a.md: &lt;bad&gt;</li>" in page
    assert 'class="callout"' not in bidx.render_html([_issue("UI-1")])


def test_render_html_puts_the_clone_position_inline_or_in_a_callout():
    level = bidx.render_html([_issue("UI-1")], position=("abc1234", 0))
    assert '<span class="pos"' in level and "level with" in level
    behind = bidx.render_html([_issue("UI-1")], position=("abc1234", 3))
    assert '<div class="callout"><strong>This clone is 3 commit(s) behind' in behind
    assert '<span class="pos"' not in behind


# --- the recorded lane: field (LANES-10) -------------------------------------

def test_lane_stays_on_a_landed_issue_and_leaves_with_a_released_one():
    lane = "UI-1@2026-10-07"
    assert bidx.lane_problems([_issue("UI-1", status="verified", lane=lane),
                               _issue("UI-2", status="closed", closed="2026-10-07", lane=lane)]) == []
    out = bidx.lane_problems([_issue("UI-3", status="open", lane=lane)])
    assert len(out) == 1 and "on a `open` issue" in out[0] and "released" in out[0]


def test_lane_problems_flag_a_malformed_value_and_two_heads_in_one_lane():
    lane = "LANES-20@2026-10-07"
    issues = [_claimed("LANES-20", ACTIVE_MK, lane=lane),
              _claimed("LANES-21", PENDING_MK, lane=lane),
              _claimed("LANES-22", _reserved("LANES-21"), lane="lanes twenty")]
    out = bidx.lane_problems(issues)
    assert any("2 ACTIVE/PENDING issues (LANES-20, LANES-21)" in p for p in out)
    assert any("`lane: lanes twenty` is not `<ID>@<YYYY-MM-DD>`" in p for p in out)


def test_a_lane_between_issues_and_a_pre_field_claim_are_both_legal():
    lane = "LANES-20@2026-10-07"
    issues = [_claimed("LANES-21", _reserved("LANES-20"), lane=lane),   # lead landed, next not flipped
              _claimed("LANES-9", _reserved("LANES-21"), lane=lane),
              _claimed("INFRA-100", ACTIVE_MK)]                          # claimed before the field
    assert bidx.lane_problems(issues) == []


def test_a_lane_shows_its_landed_issues_until_the_last_one_lands():
    lane = "LANES-22@2026-10-07"
    issues = [_issue("LANES-22", status="closed", closed="2026-10-07", lane=lane),
              _claimed("LANES-10", ACTIVE_MK, lane=lane),
              _issue("LANES-5", status="closed", closed="2026-10-07", lane="LANES-5@2026-10-01")]
    (ln,) = bidx.lanes_in_flight(issues)
    assert [m["id"] for m in ln["members"]] == ["LANES-22", "LANES-10"]
    assert [bidx.lane_member_state(m) for m in ln["members"]] == ["closed", "active"]
    assert bidx.lane_name(ln) == "LANES-22/10" and ln["lead"]["id"] == "LANES-22"
    page = bidx.render_html(issues)
    assert 'class="st st-closed"' in page and "<b>1</b> in progress" in page
    assert "title for LANES-22" in page.split('class="lanes"')[1].split("</section>")[0]
    # the last issue lands: the lane is gone, its issues remain in the closed table
    issues[1] = _issue("LANES-10", status="verified", lane=lane)
    assert bidx.lanes_in_flight(issues) == []


def test_the_recorded_lane_keeps_a_slice_together_after_its_lead_lands():
    lane = "LANES-20@2026-10-07"
    issues = [_claimed("LANES-9", _reserved("LANES-21"), lane=lane),
              _claimed("LANES-21", _reserved("LANES-20"), lane=lane),
              _issue("LANES-20", status="verified", lane=lane)]
    (ln,) = bidx.lanes_in_flight(issues)
    assert ln["key"] == lane and [m["id"] for m in ln["members"]] == ["LANES-20", "LANES-21", "LANES-9"]
    assert bidx.lane_member_state(ln["members"][0]) == "landed"
    assert bidx.lane_member_note(ln, ln["members"][1]) == ""     # its lead is right there
    assert bidx.lane_label(ln)["name"] == "LANES-20/21/9" and bidx.lane_label(ln)["where"] == "between issues"
    # a lead that landed before the field existed is not in the lane: the reservation says so
    issues[2] = _issue("LANES-20", status="verified")
    (ln,) = bidx.lanes_in_flight(issues)
    assert bidx.lane_member_note(ln, ln["members"][0]) == "queued behind LANES-20, no longer claimed"


def test_a_recorded_reservation_joins_a_pre_field_lead_under_the_derived_key():
    issues = [_claimed("LANES-20", ACTIVE_MK),                                  # no lane: field
              _claimed("LANES-21", _reserved("LANES-20"), lane="LANES-20@2026-10-07")]
    (ln,) = bidx.lanes_in_flight(issues)
    assert ln["key"] == "LANES-20@2026-10-07" and len(ln["members"]) == 2


def test_the_card_is_named_by_the_active_issue_even_when_it_is_not_the_lead():
    lane = "LANES-20@2026-10-07"
    active = ACTIVE_MK.replace("lanes-lanes-20", "lanes-lanes-21").replace("lanes-20-work", "lanes-21-work")
    issues = [_claimed("LANES-21", active.replace("**ACTIVE LANE.**", "**ACTIVE LANE.** queued behind LANES-20"),
                       lane=lane),
              _claimed("LANES-9", _reserved("LANES-21"), lane=lane)]
    (ln,) = bidx.lanes_in_flight(issues)
    assert ln["head"]["id"] == "LANES-21"
    lb = bidx.lane_label(ln)
    assert lb["name"] == "LANES-20/21/9" and lb["where"] == "lanes-lanes-21" and lb["branch"] == "lanes-21-work"


def test_index_md_and_report_group_claims_by_lane_and_list_each_once(capsys):
    lane = "LANES-20@2026-10-07"
    issues = [_claimed("LANES-20", ACTIVE_MK, lane=lane),
              _claimed("LANES-21", _reserved("LANES-20"), lane=lane),
              _issue("UI-1")]
    md = bidx.render_index(issues)
    assert "## In progress — 2 claimed · 1 lane" in md
    assert "**LANES-20/21** · `lanes-lanes-20` (`lanes-20-work`)" in md and f"lane `{lane}`" in md
    assert md.index("## In progress") < md.index("## Open / blocked / paused")
    assert md.count("[LANES-21](") == 1 and md.index("- active · [LANES-20]") < md.index("- reserved · [LANES-21]")
    for i in issues:
        i["_age"] = bidx._age(i.get("opened"))
    bidx.render_report(issues, "kyle")
    out = capsys.readouterr().out
    assert out.index("IN PROGRESS — 2 claimed · 1 lane") < out.index("BACKLOG (kyle)")
    assert "LANES-20/21 · lanes-lanes-20 [lanes-20-work]" in out and f"lane {lane}" in out
    assert out.count("reserved    LANES-21") == 1 and "     LANES-21 " not in out.split("BACKLOG (kyle)")[1]


def test_a_lane_is_named_after_its_slice():
    def ln(key, *ids):
        ms = [_claimed(i, PENDING_MK) for i in ids]
        return {"key": key, "members": ms, "lead": ms[0], "head": ms[0], "claimed": None}
    assert bidx.lane_name(ln("INFRA-98@2026-10-07", "INFRA-98", "INFRA-89")) == "INFRA-98/89"
    assert bidx.lane_name(ln("LANES-22@2026-10-07", "LANES-22", "INFRA-100")) == "LANES-22/INFRA-100"
    assert bidx.lane_name(ln("UI-3", "UI-3")) == "UI-3"


# --- the verified status + backfill ----------------------------------------

RESOLVED_BODY = """# X-1 — thing

## Context

Stuff.

## Current status

Verified 2026-09-02.

## Resolution

Shipped by **`feat(ui): two-tier viewer tabs (UI-1)`** in `frontend/src/Reviewer.jsx`.
"""
STUB_BODY = """# X-2 — thing

## Resolution

(Fill on close: what settled it, with evidence / links.)
"""


def _fm(**kw):
    base = {"id": "X-1", "project": "X", "type": "story", "status": "verified",
            "priority": "normal", "blocked_on": None, "assignee": "kyle",
            "opened": "2026-08-26", "closed": None, "commit": None,
            "resolution": "done", "links": []}
    base.update(kw)
    lines = ["---"]
    for k, v in base.items():
        lines.append(f"{k}: {'null' if v is None else ('[' + ', '.join(v) + ']' if isinstance(v, list) else v)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _write_issue(root, name, fm, body):
    (root / name).write_text(fm + body, encoding="utf-8")
    meta, _ = bidx.parse_frontmatter((root / name).read_text(encoding="utf-8"))
    meta["_path"] = Path(name)
    meta["_title"] = "t"
    return meta


SUBJECTS = {"feat(ui): two-tier viewer tabs (UI-1)": ("9f8749a" + "0" * 33, "9f8749a")}


def test_resolution_section_and_cited_subjects():
    assert bidx.resolution_is_filled(RESOLVED_BODY)
    assert not bidx.resolution_is_filled(STUB_BODY)
    assert not bidx.resolution_is_filled("# no resolution heading\n")
    cited = bidx.cited_subjects(RESOLVED_BODY)
    assert cited == ["feat(ui): two-tier viewer tabs (UI-1)", "frontend/src/Reviewer.jsx"]
    assert bidx.cited_subjects("## Context\n\n`not a subject`\n\n## Resolution\n\nplain.\n") == []


def test_subject_match_is_exact_not_regex(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    it = _write_issue(tmp_path, "v.md", _fm(), RESOLVED_BODY)
    near_miss = {"feat(ui): two-tier viewer tabs (UI-1) — sources on top": ("a" * 40, "aaaaaaa"),
                 "feat(ui): two-tier viewer tabs": ("b" * 40, "bbbbbbb")}
    assert bidx.resolving_commit(it, near_miss) is None
    assert bidx.resolving_commit(it, SUBJECTS) == SUBJECTS["feat(ui): two-tier viewer tabs (UI-1)"]


def test_unresolvable_verified_flags_stub_resolution_and_missing_subject(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    stub = _write_issue(tmp_path, "stub.md", _fm(id="X-2"), STUB_BODY)
    ok = _write_issue(tmp_path, "ok.md", _fm(id="X-1"), RESOLVED_BODY)
    drift = _write_issue(tmp_path, "drift.md", _fm(id="X-3"),
                         RESOLVED_BODY.replace("(UI-1)", "(UI-1) — sources on top"))
    live = _write_issue(tmp_path, "open.md", _fm(id="X-4", status="open"), STUB_BODY)
    out = bidx.unresolvable_verified([stub, ok, drift, live], subjects=SUBJECTS, dirty=set())
    assert len(out) == 2
    assert any("stub.md" in o and "stub" in o for o in out)
    assert any("drift.md" in o and "commit subject on HEAD" in o for o in out)


def test_unresolvable_verified_exempts_a_dirty_file_from_the_subject_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    pending = _write_issue(tmp_path, "pending.md", _fm(id="X-1"), RESOLVED_BODY)
    pending_stub = _write_issue(tmp_path, "pending-stub.md", _fm(id="X-2"), STUB_BODY)
    out = bidx.unresolvable_verified([pending, pending_stub], subjects={},
                                     dirty={"pending.md", "pending-stub.md"})
    assert len(out) == 1 and "pending-stub.md" in out[0]
    out = bidx.unresolvable_verified([pending], subjects={}, dirty=set())
    assert len(out) == 1 and "pending.md" in out[0]


def test_unresolvable_verified_skips_subject_rule_when_git_cannot_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    monkeypatch.setattr(bidx, "head_subjects", lambda: None)
    monkeypatch.setattr(bidx, "dirty_backlog_paths", lambda: None)
    it = _write_issue(tmp_path, "v.md", _fm(), RESOLVED_BODY)
    assert bidx.unresolvable_verified([it]) == []


# --- the doc loop ----------------------------------------------------------

DOCUMENTED_BODY = RESOLVED_BODY + "\n**Docs:** edited `docs/features/000-executor-move.md` (surface table).\n"


def test_is_docs_lane_reads_the_configured_list(monkeypatch):
    # defaults: docs/ and root *.md
    for p in ("docs/features/x.md", "docs/backlog/UI/UI-1-x.md", "CLAUDE.md", "README.md", "./docs/x.md"):
        assert bidx.is_docs_lane(p), p
    for p in ("modules/dwg_io.py", "tests/test_x.py", ".github/workflows/test.yml",
              ".claude/skills/worktree-increment/SKILL.md", ".gitignore", "requirements.txt",
              "docs.py", "drive/Redline-CAD/notes.md", "sub/README.md"):
        assert not bidx.is_docs_lane(p), p
    # a project widens it: another prefix, an exact file, a different glob
    monkeypatch.setattr(bidx, "DOCS_LANE_PREFIXES", ("docs/", "drive/", "*.md", "*.txt", "mkdocs.yml"))
    for p in ("drive/Redline-CAD/notes.md", "NOTES.txt", "mkdocs.yml", "docs\\x.md"):
        assert bidx.is_docs_lane(p), p
    assert not bidx.is_docs_lane("mkdocs.yml.bak") and not bidx.is_docs_lane("src/mkdocs.yml")


def test_has_docs_line_accepts_bare_bold_and_bulleted_forms_inside_the_resolution():
    for line in ("Docs: nothing — no documented behavior changed.",
                 "**Docs:** edited `x.md`.", "- **Docs:** edited `x.md`.", "* Docs: queued DOC-99.",
                 "  Docs: indented is fine."):
        assert bidx.has_docs_line(RESOLVED_BODY + line + "\n"), line
    assert not bidx.has_docs_line(RESOLVED_BODY)
    assert not bidx.has_docs_line(RESOLVED_BODY.replace("## Current status\n", "## Current status\n\nDocs: here\n"))
    assert not bidx.has_docs_line(RESOLVED_BODY + "The docs: were fine, see Docs below.\n")


def test_undocumented_verified_flags_a_code_change_without_the_line(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    code = _write_issue(tmp_path, "code.md", _fm(id="X-1"), RESOLVED_BODY)
    documented = _write_issue(tmp_path, "documented.md", _fm(id="X-2"), DOCUMENTED_BODY)
    docs_only = _write_issue(tmp_path, "docs-only.md", _fm(id="X-3"), RESOLVED_BODY)
    live = _write_issue(tmp_path, "open.md", _fm(id="X-4", status="open"), RESOLVED_BODY)
    touched = {"X-1": {"modules/dwg_io.py", "docs/backlog/X/X-1.md", "tests/test_dwg_io.py",
                       ".github/workflows/test.yml", "scripts/x.py"},
               "X-2": {"modules/dwg_io.py"},
               "X-3": {"docs/features/001-dwg-io.md", "docs/backlog/X/X-3.md", "CLAUDE.md"},
               "X-4": {"modules/dwg_io.py"}}
    out = bidx.undocumented_verified([code, documented, docs_only, live], subjects=SUBJECTS,
                                     dirty=set(), touched=lambda it: touched[it["id"]])
    assert len(out) == 1 and out[0].startswith("code.md:")
    assert ".github/workflows/test.yml, modules/dwg_io.py, scripts/x.py (+1 more)" in out[0]
    assert "`Docs:`" in out[0]


def test_undocumented_verified_reads_the_dirty_tree_for_a_dirty_issue(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    monkeypatch.setattr(bidx, "dirty_paths", lambda: {"modules/dwg_io.py", "v.md"})
    monkeypatch.setattr(bidx, "commit_paths", lambda h: pytest.fail("clean-path lookup used for a dirty issue"))
    it = _write_issue(tmp_path, "v.md", _fm(), RESOLVED_BODY)
    out = bidx.undocumented_verified([it], subjects={}, dirty={"v.md"})
    assert len(out) == 1 and "modules/dwg_io.py" in out[0]
    monkeypatch.setattr(bidx, "dirty_paths", lambda: {"docs/PROJECT_STATE.md", "v.md"})
    assert bidx.undocumented_verified([it], subjects={}, dirty={"v.md"}) == []


def test_undocumented_verified_reads_the_resolving_commit_for_a_clean_issue(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    seen = []
    monkeypatch.setattr(bidx, "commit_paths", lambda h: seen.append(h) or {"frontend/src/Reviewer.jsx"})
    it = _write_issue(tmp_path, "v.md", _fm(), RESOLVED_BODY)
    out = bidx.undocumented_verified([it], subjects=SUBJECTS, dirty=set())
    assert seen == [SUBJECTS["feat(ui): two-tier viewer tabs (UI-1)"][0]]
    assert len(out) == 1 and "frontend/src/Reviewer.jsx" in out[0]
    assert bidx.undocumented_verified([it], subjects={}, dirty=set()) == []


def test_undocumented_verified_skips_when_git_cannot_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    monkeypatch.setattr(bidx, "head_subjects", lambda: None)
    monkeypatch.setattr(bidx, "dirty_backlog_paths", lambda: None)
    it = _write_issue(tmp_path, "v.md", _fm(), RESOLVED_BODY)
    assert bidx.undocumented_verified([it]) == []
    monkeypatch.setattr(bidx, "commit_paths", lambda h: None)
    assert bidx.undocumented_verified([it], subjects=SUBJECTS, dirty=set()) == []


def test_commit_and_dirty_paths_survive_spaces_apostrophes_and_non_ascii(tmp_path, monkeypatch):
    def g(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True,
                              encoding="utf-8", check=True).stdout
    g("init", "-q")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    odd = "docs/session-assets/2026-09-16 - Kyle - the doc loop's three holes — x.md"
    (tmp_path / "docs" / "session-assets").mkdir(parents=True)
    (tmp_path / odd).write_text("x", encoding="utf-8")
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "a.py").write_text("x", encoding="utf-8")
    g("add", "-A")
    g("commit", "-q", "-m", "c1")
    head = g("rev-parse", "HEAD").strip()
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    assert bidx.commit_paths(head) == {odd, "modules/a.py"}
    (tmp_path / "modules" / "a.py").write_text("y", encoding="utf-8")
    (tmp_path / "new file → here.txt").write_text("z", encoding="utf-8")
    g("mv", odd, "docs/session-assets/renamed — x.md")
    assert bidx.dirty_paths() == {"modules/a.py", "new file → here.txt",
                                  "docs/session-assets/renamed — x.md"}


def test_dirty_backlog_paths_reads_the_configured_dir(repo, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", repo)
    monkeypatch.setattr(bidx, "BACKLOG_REL", "work/issues")
    put(repo, "UI-1", backlog_rel="work/issues")
    put(repo, "UI-2", backlog_rel="docs/backlog")
    assert bidx.dirty_backlog_paths() == {"work/issues/UI/UI-1-a-thing.md"}


def test_backfill_closes_a_resolvable_verified_issue_and_only_that(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    it = _write_issue(tmp_path, "v.md", _fm(links=["UI-37", "UI-38"]), RESOLVED_BODY)
    stub = _write_issue(tmp_path, "s.md", _fm(id="X-2"), STUB_BODY)
    before = (tmp_path / "v.md").read_text(encoding="utf-8")
    closed, skipped = bidx.backfill_verified([it, stub], subjects=SUBJECTS, today="2026-09-03")
    assert [(i["id"], h) for i, h in closed] == [("X-1", "9f8749a")]
    assert [i["id"] for i, _ in skipped] == ["X-2"]
    after = (tmp_path / "v.md").read_text(encoding="utf-8")
    meta, body = bidx.parse_frontmatter(after)
    assert meta["status"] == "closed" and meta["commit"] == "9f8749a" and meta["closed"] == "2026-09-03"
    assert meta["links"] == ["UI-37", "UI-38"]
    assert body == bidx.parse_frontmatter(before)[1]
    diff = [(a, b) for a, b in zip(before.split("\n"), after.split("\n")) if a != b]
    assert diff == [("status: verified", "status: closed"), ("closed: null", "closed: 2026-09-03"),
                    ("commit: null", "commit: 9f8749a")]
    assert bidx.parse_frontmatter((tmp_path / "s.md").read_text(encoding="utf-8"))[0]["status"] == "verified"


def test_backfill_skips_an_undocumented_code_issue_and_closes_a_documented_one(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    monkeypatch.setattr(bidx, "commit_paths", lambda h: {"modules/dwg_io.py", "docs/backlog/X/X-1.md"})
    bare = _write_issue(tmp_path, "bare.md", _fm(id="X-1"), RESOLVED_BODY)
    documented = _write_issue(tmp_path, "documented.md", _fm(id="X-2"), DOCUMENTED_BODY)
    closed, skipped = bidx.backfill_verified([bare, documented], subjects=SUBJECTS, today="2026-09-16")
    assert [i["id"] for i, _ in closed] == ["X-2"]
    assert [(i["id"], "Docs:" in why and "modules/dwg_io.py" in why) for i, why in skipped] == [("X-1", True)]
    monkeypatch.setattr(bidx, "commit_paths", lambda h: {"docs/features/001-dwg-io.md", "CLAUDE.md"})
    closed, skipped = bidx.backfill_verified([bare], subjects=SUBJECTS, today="2026-09-16")
    assert [i["id"] for i, _ in closed] == ["X-1"] and skipped == []


def test_backfill_keeps_a_lane_supplied_closed_date(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    it = _write_issue(tmp_path, "v.md", _fm(closed="2026-09-02"), RESOLVED_BODY)
    bidx.backfill_verified([it], subjects=SUBJECTS, today="2026-09-05")
    meta, _ = bidx.parse_frontmatter((tmp_path / "v.md").read_text(encoding="utf-8"))
    assert meta["closed"] == "2026-09-02" and meta["status"] == "closed"


def test_backfill_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    it = _write_issue(tmp_path, "v.md", _fm(), RESOLVED_BODY)
    before = (tmp_path / "v.md").read_text(encoding="utf-8")
    closed, _ = bidx.backfill_verified([it], subjects=SUBJECTS, dry_run=True)
    assert len(closed) == 1
    assert (tmp_path / "v.md").read_text(encoding="utf-8") == before


def test_backfill_never_invents_a_resolution_and_refuses_a_verified_wont_do(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    null = _write_issue(tmp_path, "n.md", _fm(id="X-1", resolution=None), RESOLVED_BODY)
    wont = _write_issue(tmp_path, "w.md", _fm(id="X-2", resolution="wont-do"), RESOLVED_BODY)
    done = _write_issue(tmp_path, "d.md", _fm(id="X-3", resolution="done"), RESOLVED_BODY)
    closed, skipped = bidx.backfill_verified([null, wont, done], subjects=SUBJECTS, today="2026-09-27")
    assert [i["id"] for i, _ in closed] == ["X-3"]
    reasons = {i["id"]: why for i, why in skipped}
    assert "resolution: null" in reasons["X-1"] and "wont-do" in reasons["X-2"]


def test_backfill_cli_refuses_on_a_non_certifying_machine(monkeypatch, capsys):
    monkeypatch.setattr(bidx, "MACHINE", dict(bidx.MACHINE, certifies=False, id="other-box"))
    touched = []
    monkeypatch.setattr(bidx, "backfill_verified", lambda *a, **k: touched.append(1) or ([], []))
    monkeypatch.setattr(bidx, "load_issues", lambda: ([], []))
    assert bidx.main(["--backfill", "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "other-box" in err and not touched


def test_backfill_commit_stages_by_path_and_never_pushes(repo, monkeypatch):
    bl = repo / "docs" / "backlog" / "UI"
    bl.mkdir(parents=True)
    (bl / "UI-1-x.md").write_text(_fm(id="UI-1", project="UI") + DOCUMENTED_BODY, encoding="utf-8")
    (repo / "unrelated.txt").write_text("x", encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "feat(ui): two-tier viewer tabs (UI-1)", cwd=repo)
    (repo / "unrelated.txt").write_text("dirty, must not be swept", encoding="utf-8")
    for k, v in bidx.settings(repo, {"backlog": {"projects": ["UI"]}}).items():
        if k in ("ROOT", "BACKLOG", "BACKLOG_REL", "INDEX", "HTML_VIEW", "PROJECTS"):
            monkeypatch.setattr(bidx, k, v)
    assert bidx.certifies()
    assert bidx.main(["--backfill", "--commit"]) == 0
    assert git("log", "-1", "--format=%s", cwd=repo) == "docs(backlog): close UI-1 — backfill resolving commit hash"
    assert git("show", "--stat", "--format=", "HEAD", cwd=repo).count("|") == 1
    assert "UI-1-x.md" in git("show", "--stat", "--format=", "HEAD", cwd=repo)
    assert "unrelated.txt" in git("status", "--porcelain", cwd=repo)
    meta, _ = bidx.parse_frontmatter((bl / "UI-1-x.md").read_text(encoding="utf-8"))
    resolving = git("log", "--format=%h", "--grep=two-tier", cwd=repo)
    assert meta["status"] == "closed" and meta["commit"] == resolving
    issues, problems = bidx.load_issues()
    assert not problems and bidx.check_problems(issues, problems) == []



# --- concurrent certifying machines (LANES-6) -------------------------------

def _point(monkeypatch, root):
    """Aim the module at `root` (a solo-mode clone, so it certifies)."""
    for k, v in bidx.settings(root, {"backlog": {"projects": ["UI"]}}).items():
        if k in ("ROOT", "BACKLOG", "BACKLOG_REL", "INDEX", "HTML_VIEW", "PROJECTS", "MAIN_BRANCH"):
            monkeypatch.setattr(bidx, k, v)


def _two_clones(tmp_path, monkeypatch):
    """A bare `origin` holding one verified issue whose resolving commit is dated
    2026-09-01, and two clones of it — two certifying machines."""
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    seed = tmp_path / "seed"
    git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=seed)
    git("config", "user.name", "Tester", cwd=seed)
    bl = seed / "docs" / "backlog" / "UI"
    bl.mkdir(parents=True)
    (bl / "UI-1-x.md").write_text(_fm(id="UI-1", project="UI") + DOCUMENTED_BODY, encoding="utf-8")
    git("add", "-A", cwd=seed)
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-09-01T12:00:00+00:00")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-09-01T12:00:00+00:00")
    git("commit", "-q", "-m", "feat(ui): two-tier viewer tabs (UI-1)", cwd=seed)
    monkeypatch.delenv("GIT_COMMITTER_DATE")
    monkeypatch.delenv("GIT_AUTHOR_DATE")
    git("push", "-q", "origin", "main", cwd=seed)
    clones = []
    for name in ("mac", "win"):
        c = tmp_path / name
        git("clone", "-q", str(origin), str(c), cwd=tmp_path)
        git("config", "user.email", f"{name}@example.com", cwd=c)
        git("config", "user.name", "Tester", cwd=c)
        clones.append(c)
    return origin, clones


def test_backfill_closed_date_is_the_resolving_commits_date_not_today(tmp_path, monkeypatch):
    _, (mac, _) = _two_clones(tmp_path, monkeypatch)
    _point(monkeypatch, mac)
    issues, _ = bidx.load_issues()
    closed, _ = bidx.backfill_verified(issues, today="2099-01-01")
    meta, _ = bidx.parse_frontmatter((mac / "docs/backlog/UI/UI-1-x.md").read_text(encoding="utf-8"))
    assert meta["closed"] == "2026-09-01"
    assert len(meta["commit"]) == 7


def test_backfill_push_on_two_machines_converges_without_a_conflict(tmp_path, monkeypatch):
    origin, (mac, win) = _two_clones(tmp_path, monkeypatch)
    # Both machines start up from the same tip. win closes and commits first, but has
    # not pushed when mac's --push lands — the race a single-writer gate existed for.
    _point(monkeypatch, win)
    assert bidx.main(["--backfill", "--commit"]) == 0
    _point(monkeypatch, mac)
    assert bidx.main(["--backfill", "--push"]) == 0
    _point(monkeypatch, win)
    ok, msg = bidx.push_backfill()
    assert ok, msg
    tip = git("rev-parse", "main", cwd=origin)
    for c in (mac, win):
        assert git("rev-parse", "HEAD", cwd=c) == tip
        assert git("status", "--porcelain", "--untracked-files=no", cwd=c) == ""
    log = git("log", "--format=%s", "main", cwd=origin).splitlines()
    assert log.count("docs(backlog): close UI-1 — backfill resolving commit hash") == 1
    meta, _ = bidx.parse_frontmatter(git("show", "main:docs/backlog/UI/UI-1-x.md", cwd=origin))
    assert meta["status"] == "closed" and meta["closed"] == "2026-09-01"


def test_backfill_push_on_a_stale_clone_fast_forwards_and_closes_nothing_twice(tmp_path, monkeypatch):
    origin, (mac, win) = _two_clones(tmp_path, monkeypatch)
    _point(monkeypatch, mac)
    assert bidx.main(["--backfill", "--push"]) == 0
    _point(monkeypatch, win)                      # never pulled
    assert bidx.main(["--backfill", "--push"]) == 0
    assert git("rev-parse", "HEAD", cwd=win) == git("rev-parse", "main", cwd=origin)
    assert git("rev-list", "--count", "main", cwd=origin) == "2"


def test_backfill_push_keeps_the_commit_local_when_main_carries_other_work(tmp_path, monkeypatch, capsys):
    origin, (mac, _) = _two_clones(tmp_path, monkeypatch)
    (mac / "src.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "src.py", cwd=mac)
    git("commit", "-q", "-m", "feat: code on local main", cwd=mac)
    _point(monkeypatch, mac)
    before = git("rev-parse", "main", cwd=origin)
    assert bidx.main(["--backfill", "--push"]) == 1
    assert "not pushed" in capsys.readouterr().err
    assert git("rev-parse", "main", cwd=origin) == before
    assert git("log", "-1", "--format=%s", cwd=mac).startswith("docs(backlog): close UI-1")


def test_backfill_push_refuses_off_the_main_branch_and_with_dry_run(tmp_path, monkeypatch, capsys):
    _, (mac, _) = _two_clones(tmp_path, monkeypatch)
    _point(monkeypatch, mac)
    assert bidx.main(["--backfill", "--push", "--dry-run"]) == 2
    git("checkout", "-q", "-b", "topic", cwd=mac)
    assert bidx.main(["--backfill", "--push"]) == 1
    assert "topic" in capsys.readouterr().err

def test_views_bucket_verified_between_live_and_closed():
    issues = [_issue("UI-1"), _issue("UI-2", status="verified"),
              _issue("UI-3", status="closed", closed="2026-09-01", commit="abc1234")]
    md = bidx.render_index(issues)
    assert "1 live" in md and "1 verified" in md and "1 closed" in md
    assert "kyle's next startup fills" in md
    assert md.index("UI-1") < md.index("## Verified") < md.index("UI-2") < md.index("## Closed") < md.index("UI-3")
    page = bidx.render_html(issues)
    assert "<b>1</b> live" in page and "<b>1</b> verified" in page and "<b>1</b> closed" in page
    assert page.index("awaiting kyle's close") < page.index(">UI-2</a>") < page.index("<summary>Closed ")
    assert 'data-status="verified"' in page and ".s-verified" in page


def test_report_lists_verified_as_its_own_bucket(capsys, monkeypatch):
    issues = [_issue("UI-1"), _issue("UI-2", status="verified")]
    for i in issues:
        i["_age"] = 1
    bidx.render_report(issues, "kyle")
    out = capsys.readouterr().out
    assert "1 live" in out and "Verified — landed, awaiting close (1; run" in out
    assert out.index("UI-1") < out.index("Verified") < out.index("UI-2")
    monkeypatch.setattr(bidx, "MACHINE", dict(bidx.MACHINE, certifies=False))
    bidx.render_report(issues, "mike")
    assert "awaiting kyle's close — read-only here" in capsys.readouterr().out


def test_report_who_defaults_to_this_machine_and_validates(capsys, monkeypatch):
    monkeypatch.setattr(bidx, "load_issues", lambda: ([], []))
    assert bidx.main(["--report"]) == 0
    assert "BACKLOG (kyle)" in capsys.readouterr().out
    assert bidx.main(["--report", "--who", "bob"]) == 2
    assert "--who must be one of kyle, mike or both" in capsys.readouterr().err
    assert bidx.main(["--report", "--who", "both"]) == 0


# --- the resolution field ---------------------------------------------------

def test_resolution_rules_follow_status_commit_and_cutover(monkeypatch):
    issues = [
        _issue("UI-1", status="open", resolution="done"),
        _issue("UI-2", status="verified", resolution=None),
        _issue("UI-3", status="closed", closed="2026-09-27", resolution=None),
        _issue("UI-4", status="closed", closed="2026-09-26", resolution=None),
        _issue("UI-5", status="closed", closed="2026-09-27", resolution="wont-do", commit="abc1234"),
        _issue("UI-6", status="closed", closed="2026-09-27", resolution="wont-do", commit=None),
        _issue("UI-7", status="closed", closed="2026-09-27", resolution="done", commit="abc1234"),
        _issue("UI-8", status="closed", closed=None, resolution=None),
    ]
    hits = lambda out, iid: [p for p in out if f"/{iid}-x.md" in p]
    # default: always required
    out = bidx.resolution_problems(issues)
    assert len(hits(out, "UI-1")) == 1 and "open issue" in hits(out, "UI-1")[0]
    assert len(hits(out, "UI-2")) == 1 and "verified" in hits(out, "UI-2")[0]
    assert len(hits(out, "UI-3")) == 1 and len(hits(out, "UI-4")) == 1
    assert len(hits(out, "UI-5")) == 1 and "wont-do" in hits(out, "UI-5")[0]
    for ok in ("UI-6", "UI-7", "UI-8"):
        assert hits(out, ok) == [], ok
    # a cutover date leaves older closes alone
    monkeypatch.setattr(bidx, "RESOLUTION_CUTOVER", "2026-09-27")
    out = bidx.resolution_problems(issues)
    assert len(hits(out, "UI-3")) == 1 and "2026-09-27" in hits(out, "UI-3")[0]
    assert hits(out, "UI-4") == []


TEST_CONFIG = '''[backlog]
projects = ["UI", "INFRA"]
[[operators]]
name = "Tester"
platform = "{platform}"
id = "test-box"
short = "kyle"
certifies = true
[[operators]]
name = "Other"
platform = "win32"
id = "other-box"
short = "mike"
certifies = false
may_edit_code = false
'''.format(platform=sys.platform)


def test_check_cli_runs_against_root_and_reports_problems(repo, capsys):
    (repo / ".claude" / "lanes").mkdir(parents=True)
    (repo / ".claude" / "lanes" / "config.toml").write_text(TEST_CONFIG, encoding="utf-8")
    put(repo, "UI-1", status="closed", closed="2026-09-27", resolution="null",
        resolution_body="closed in a test.")
    assert bidx.main(["--root", str(repo), "--check"]) == 1
    err = capsys.readouterr().err
    assert "UI-1" in err and "without a resolution" in err and "FAILED" in err
    put(repo, "UI-1", status="closed", closed="2026-09-27", resolution="wont-do",
        resolution_body="closed in a test.")
    assert bidx.main(["--root", str(repo), "--check"]) == 0
    assert "backlog check OK — 1 issues" in capsys.readouterr().out


def test_html_closed_rows_carry_the_resolution_and_search_covers_the_new_keys():
    page = bidx.render_html([_issue("UI-1", status="closed", closed="2026-09-27",
                                    resolution="wont-do", reported_by="mike")])
    assert 'data-resolution="wont-do"' in page and "Resolution" in page
    row = page[page.index("<tr data-project"):]
    assert "wont-do" in row.split("</tr>")[0]
    assert "mike" in row.split("</tr>")[0]
    assert 'data-field="assignee"' in page and 'data-field="owner"' not in page


# --- epics -------------------------------------------------------------------

def test_dangling_epics_flags_missing_non_epic_and_self_parents():
    epic = _issue("PROD-16", type="epic")
    story = _issue("PROD-1")
    ok = _issue("PROD-2", epic="PROD-16")
    missing = _issue("PROD-3", epic="PROD-99")
    not_epic = _issue("PROD-4", epic="PROD-1")
    selfie = _issue("PROD-5", type="epic", epic="PROD-5")
    out = bidx.dangling_epics([epic, story, ok, missing, not_epic, selfie])
    assert len(out) == 3
    assert any("PROD-3" in p and "does not exist" in p for p in out)
    assert any("PROD-4" in p and "not an epic" in p for p in out)
    assert any("PROD-5" in p and "names itself" in p for p in out)


def test_an_epic_may_nest_under_another_epic():
    umbrella = _issue("PROD-16", type="epic")
    phase = _issue("PROD-14", type="epic", epic="PROD-16")
    assert bidx.dangling_epics([umbrella, phase]) == []


def test_epic_rollup_counts_children_by_status_in_vocabulary_order():
    issues = [_issue("PROD-14", type="epic"),
              _issue("PROD-2", epic="PROD-14", status="in-progress"),
              _issue("UI-51", epic="PROD-14", status="blocked"),
              _issue("INFRA-51", epic="PROD-14", status="blocked"),
              _issue("PROD-1"),
              _issue("BD-31", type="epic", epic="PROD-16")]
    assert bidx.epic_rollup(issues, "PROD-14") == {"in-progress": 1, "blocked": 2}
    assert list(bidx.epic_rollup(issues, "PROD-14")) == ["in-progress", "blocked"]
    assert bidx.epic_rollup(issues, "PROD-16") == {"open": 1}
    assert bidx.epic_rollup(issues, "PROD-1") == {}


def test_html_rows_carry_the_epic_family_and_the_facet_lists_every_epic():
    issues = [_issue("PROD-16", type="epic"),
              _issue("PROD-14", type="epic", epic="PROD-16"),
              _issue("UI-51", epic="PROD-14"),
              _issue("PIPE-1")]
    out = bidx.render_html(issues)
    assert 'data-field="epic"' in out
    for chip in ("PROD-14", "PROD-16", "—"):
        assert f'value="{chip}"' in out
    assert bidx._epic_family(issues[0]) == "PROD-16"
    assert bidx._epic_family(issues[1]) == "PROD-14 PROD-16"
    assert bidx._epic_family(issues[2]) == "PROD-14"
    assert bidx._epic_family(issues[3]) == "—"
    assert "d.epics.split(' ')" in out and "checked('epic')" in out and 'data-key="epic"' in out


def test_html_omits_the_epic_facet_when_no_epic_exists():
    out = bidx.render_html([_issue("PIPE-1"), _issue("PIPE-2")])
    assert 'data-field="epic"' not in out
    assert 'data-epics="—"' in out


def test_index_md_has_the_epic_column():
    out = bidx.render_index([_issue("PROD-14", type="epic"), _issue("UI-51", epic="PROD-14")])
    assert "| Epic |" in out and "| PROD-14 |" in out


def test_report_rolls_each_live_epic_up_into_one_line(capsys):
    issues = [_issue("PROD-14", type="epic", priority="high"),
              _issue("UI-51", epic="PROD-14", status="blocked"),
              _issue("PROD-2", epic="PROD-14", status="in-progress"),
              _issue("PROD-99", type="epic", status="closed"),
              _issue("PIPE-1")]
    for i in issues:
        i["_age"] = 3
    bidx.render_report(issues, "kyle")
    out = capsys.readouterr().out
    assert "Epics — child roll-up (1)" in out
    line = next(l for l in out.splitlines() if l.strip().startswith("PROD-14") and "children" in l)
    assert "2 children" in line and "in-progress 1" in line and "blocked 1" in line
    assert "PROD-99" not in out.split("Epics — child roll-up")[1]


def test_report_has_no_rollup_section_without_a_live_epic(capsys):
    issues = [_issue("PIPE-1")]
    issues[0]["_age"] = 1
    bidx.render_report(issues, "kyle")
    assert "child roll-up" not in capsys.readouterr().out


def test_epic_field_parses_from_frontmatter_and_check_reads_it(tmp_path, monkeypatch):
    monkeypatch.setattr(bidx, "ROOT", tmp_path)
    parent = _write_issue(tmp_path, "p.md", _fm(id="X-1", type="epic", status="open"), "# X-1 — p\n")
    child = _write_issue(tmp_path, "c.md",
                         _fm(id="X-2", status="open").replace("links: []", "links: []\nepic: X-1"),
                         "# X-2 — c\n")
    assert child["epic"] == "X-1"
    assert bidx.dangling_epics([parent, child]) == []
    orphan = _write_issue(tmp_path, "o.md",
                          _fm(id="X-3", status="open").replace("links: []", "links: []\nepic: X-9"),
                          "# X-3 — o\n")
    assert len(bidx.dangling_epics([parent, child, orphan])) == 1


# --- --serve: the view generates on READ, not on write -------------------------

import socket as _socket
import threading
import time
import urllib.error
import urllib.request


def _free_port():
    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serving(port):
    t = threading.Thread(target=bidx.serve, kwargs={"port": port}, daemon=True)
    t.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).read()
            return
        except Exception:
            time.sleep(0.05)
    pytest.skip("serve() did not come up in 10s")


@pytest.fixture
def served_repo(repo, monkeypatch):
    for k, v in bidx.settings(repo, {"backlog": {"projects": ["INFRA"]}}).items():
        if k in ("ROOT", "BACKLOG", "BACKLOG_REL", "INDEX", "HTML_VIEW", "PROJECTS"):
            monkeypatch.setattr(bidx, k, v)
    return repo


def test_the_reserved_port_comes_from_config(monkeypatch):
    monkeypatch.setattr(bidx, "VIEW_PORT", 8123)
    assert bidx._reserved_port() == 8123


def test_serve_reflects_an_edit_without_any_regeneration_step(served_repo):
    port = _free_port()
    _serving(port)

    def page():
        return urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode()

    assert "SERVEPROOF" not in page()
    scratch = put(served_repo, "INFRA-9999", title="SERVEPROOF temporary fixture")
    try:
        assert "SERVEPROOF" in page()
    finally:
        scratch.unlink()
    assert "SERVEPROOF" not in page()


def test_serve_forbids_caching_and_404s_anything_but_the_view(served_repo):
    port = _free_port()
    _serving(port)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
        assert "no-store" in r.headers.get("Cache-Control", "")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
    assert exc.value.code == 404


def test_clone_position_reports_without_fetching_and_uses_the_main_branch(served_repo, monkeypatch):
    head, behind = bidx.clone_position()
    assert head is None or isinstance(head, str)
    assert isinstance(behind, int) and behind >= 0
    monkeypatch.setattr(bidx, "MAIN_BRANCH", "trunk")
    assert "origin/trunk" in bidx._banner("abc1234", 2) and "2 commit(s) behind" in bidx._banner("abc1234", 2)
    assert "origin/trunk" in bidx._banner("abc1234", 0)
    assert bidx._banner(None, 0) == ""


def test_backlog_new_accepts_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(bnew, "BACKLOG", tmp_path)
    monkeypatch.setattr(bnew, "ROOT", tmp_path)
    monkeypatch.setattr(bnew, "refs_max", lambda project, repo=None, fetch=True: 0)
    p = bnew.create_issue("UI", "x", status="verified", regen_index=False)
    assert bidx.parse_frontmatter(p.read_text(encoding="utf-8"))[0]["status"] == "verified"
    assert bidx.RESOLUTION_STUB in bnew.BODY_STUB
    assert not bidx.resolution_is_filled(p.read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        bnew.create_issue("UI", "y", status="done", regen_index=False)


def test_one_person_on_two_certifying_machines_appears_once(tmp_path):
    """LANES-3: two rows sharing `kyle` are one person -- one certifier, one assignee."""
    raw = {"operators": [
        {"name": "kylemullet", "platform": "darwin", "id": "kyle-mac", "short": "kyle", "certifies": True},
        {"name": "kylemullet", "platform": "win32", "id": "kyle-win", "short": "kyle", "certifies": True},
        {"name": "Mike", "platform": "win32", "id": "mike-win", "short": "mike", "may_edit_code": False},
    ]}
    s = bidx.settings(root=tmp_path, raw=raw)
    assert s["CERTIFIER_LABEL"] == "kyle's" and s["DEFAULT_ASSIGNEE"] == "kyle"
    assert s["ASSIGNEES"] == ("kyle", "mike", "shared") and s["REPORTERS"] == ("claude", "kyle", "mike")


# --- --isolated: close from a throwaway worktree at origin/<main> (LANES-23) ---

def _worktrees(c):
    return [l for l in git("worktree", "list", "--porcelain", cwd=c).splitlines() if l.startswith("worktree ")]


def test_isolated_push_closes_past_another_sessions_unpushed_claim(tmp_path, monkeypatch):
    """The shared main clone carries another session's claim, committed and not yet
    pushed, plus an edit in progress: the in-place --push refuses on the divergence once
    origin moves; --isolated closes on origin and leaves every byte of the clone alone."""
    origin, (mac, win) = _two_clones(tmp_path, monkeypatch)
    (win / "note.md").write_text("origin moved\n", encoding="utf-8")   # origin moves on
    git("add", "note.md", cwd=win)
    git("commit", "-q", "-m", "docs: elsewhere", cwd=win)
    git("push", "-q", "origin", "main", cwd=win)
    claim = mac / "docs/backlog/UI/UI-2-y.md"
    claim.write_text(_fm(id="UI-2", project="UI", status="open", resolution=None) + "# UI-2 — y\n",
                     encoding="utf-8")
    git("add", str(claim), cwd=mac)
    git("commit", "-q", "-m", "docs(backlog): claim UI-2", cwd=mac)
    (mac / "wip.txt").write_text("mid-edit\n", encoding="utf-8")
    head = git("rev-parse", "HEAD", cwd=mac)
    _point(monkeypatch, mac)
    assert bidx.main(["--backfill", "--push"]) == 1                     # the LANES-23 refusal
    assert bidx.main(["--backfill", "--push", "--isolated"]) == 0
    meta, _ = bidx.parse_frontmatter(git("show", "main:docs/backlog/UI/UI-1-x.md", cwd=origin))
    assert meta["status"] == "closed" and meta["closed"] == "2026-09-01"
    assert git("log", "-1", "--format=%s", "main", cwd=origin).startswith("docs(backlog): close UI-1")
    assert git("rev-parse", "HEAD", cwd=mac) == head                    # the claim, untouched
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=mac) == "main"
    assert "status: verified" in (mac / "docs/backlog/UI/UI-1-x.md").read_text(encoding="utf-8")
    assert (mac / "wip.txt").read_text(encoding="utf-8") == "mid-edit\n"
    assert git("status", "--porcelain", cwd=mac) == "?? wip.txt"
    assert len(_worktrees(mac)) == 1                                    # the throwaway is gone
    assert bidx.ROOT == mac                                             # and the module points home


def test_isolated_push_works_off_the_main_branch_and_converges_with_an_in_place_close(tmp_path, monkeypatch):
    origin, (mac, win) = _two_clones(tmp_path, monkeypatch)
    git("checkout", "-q", "-b", "some-lane", cwd=mac)
    _point(monkeypatch, win)
    assert bidx.main(["--backfill", "--push"]) == 0                     # win closed it first
    _point(monkeypatch, mac)
    assert bidx.main(["--backfill", "--push", "--isolated"]) == 0      # nothing left to close
    log = git("log", "--format=%s", "main", cwd=origin).splitlines()
    assert log.count("docs(backlog): close UI-1 — backfill resolving commit hash") == 1
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=mac) == "some-lane"
    assert len(_worktrees(mac)) == 1


def test_isolated_needs_push(tmp_path, monkeypatch, capsys):
    _, (mac, _) = _two_clones(tmp_path, monkeypatch)
    _point(monkeypatch, mac)
    assert bidx.main(["--backfill", "--commit", "--isolated"]) == 2
    assert "--isolated needs --push" in capsys.readouterr().err
