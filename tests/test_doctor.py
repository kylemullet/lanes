from datetime import datetime, timedelta

import lanes_config as lc
import lanes_doctor as ld
import lanes_init as li
from conftest import git, write_issue

NOW = datetime(2026, 10, 4, 12, 0)


def by_label(checks):
    return {c.label: c for c in checks}


def test_fresh_repo_fails_on_config_only(repo):
    checks = by_label(ld.run(repo, now=NOW))
    assert checks["config"].status == ld.FAIL and "/lanes:init" in checks["config"].detail
    assert checks["tracked"].status == ld.SKIP
    assert checks["stubs"].status == ld.WARN
    assert checks["backlog"].status == ld.WARN
    assert checks["claims"].status == ld.SKIP
    assert checks["position"].status == ld.OK and "main clone" in checks["position"].detail
    assert ld.exit_code(list(checks.values()), strict=False) == 1


def test_after_init_and_commit(repo):
    li.scaffold(repo, force=False, projects=["CORE"])
    checks = by_label(ld.run(repo, now=NOW))
    assert checks["config"].status == ld.OK and "solo mode" in checks["config"].detail
    assert checks["tracked"].status == ld.WARN and "untracked" in checks["tracked"].detail
    assert checks["version"].status == ld.OK
    assert checks["stubs"].status == ld.OK
    git("add", ".claude", cwd=repo)
    git("commit", "-q", "-m", "lanes", cwd=repo)
    checks = by_label(ld.run(repo, now=NOW))
    assert checks["tracked"].status == ld.OK
    assert checks["settings"].status == ld.WARN
    assert ld.exit_code(list(checks.values()), strict=False) == 0
    assert ld.exit_code(list(checks.values()), strict=True) == 1


def test_version_drift_and_missing_pin(repo):
    li.scaffold(repo, force=False, projects=["CORE"])
    p = repo / lc.CONFIG_REL
    p.write_text(p.read_text(encoding="utf-8").replace(f'plugin_version = "{lc.installed_version()}"', 'plugin_version = "9.9.9"'), encoding="utf-8")
    v = by_label(ld.run(repo, now=NOW))["version"]
    assert v.status == ld.WARN and "9.9.9" in v.detail and lc.installed_version() in v.detail
    p.write_text("[git]\nmain_branch = \"main\"\n", encoding="utf-8")
    v = by_label(ld.run(repo, now=NOW))["version"]
    assert v.status == ld.WARN and "pins none" in v.detail


def test_settings_pin_detected(repo):
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / ".claude" / "settings.json").write_text('{"enabledPlugins": {"lanes@lanes-marketplace": true}}', encoding="utf-8")
    assert ld.check_settings(repo).status == ld.OK


def _claims(repo, now=NOW, exempt=()):
    cfg = lc.resolve({"backlog": {"claim_marker_exempt": list(exempt)}}, user_name="t", platform="linux")
    return {c.label: c for c in ld.check_claims(repo, cfg, now=now)}


def stamp(minutes_ago, now=NOW):
    return (now - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M")


def test_young_active_claim_is_live_by_rule_even_without_evidence(repo):
    write_issue(repo, "docs/backlog", "CORE", "CORE-1", "in-progress",
                f"⏳ IN-PROGRESS ({stamp(3)}, T's session, worktree proj-core-1, branch core-1-work) — **ACTIVE LANE.** Expected files: x")
    c = _claims(repo)["claim CORE-1"]
    assert c.status == ld.OK and "younger than the 15-minute floor" in c.detail


def test_old_active_claim_without_worktree_or_branch_is_a_candidate(repo):
    write_issue(repo, "docs/backlog", "CORE", "CORE-2", "in-progress",
                f"⏳ IN-PROGRESS ({stamp(90)}, T's session, worktree proj-core-2, branch core-2-work) — **ACTIVE LANE.** Expected files: x")
    c = _claims(repo)["claim CORE-2"]
    assert c.status == ld.WARN and "STALE-CLAIM CANDIDATE" in c.detail and "never a takeover" in c.detail


def test_old_active_claim_with_branch_is_live(repo):
    git("branch", "core-3-work", cwd=repo)
    write_issue(repo, "docs/backlog", "CORE", "CORE-3", "in-progress",
                f"⏳ IN-PROGRESS ({stamp(90)}, T's session, worktree proj-core-3, branch core-3-work) — **ACTIVE LANE.** Expected files: x")
    c = _claims(repo)["claim CORE-3"]
    assert c.status == ld.OK and "branch core-3-work exists" in c.detail


def test_old_active_claim_with_worktree_is_live(repo, tmp_path):
    wt = tmp_path / "proj-core-4"
    git("worktree", "add", "-q", str(wt), "-b", "core-4-work", cwd=repo)
    write_issue(repo, "docs/backlog", "CORE", "CORE-4", "in-progress",
                f"⏳ IN-PROGRESS ({stamp(400)}, T's session, worktree proj-core-4, branch core-4-work) — **ACTIVE LANE.** Expected files: x")
    c = _claims(repo)["claim CORE-4"]
    assert c.status == ld.OK and "worktree proj-core-4 present" in c.detail


def test_pending_and_reserved_are_live_at_any_age(repo):
    write_issue(repo, "docs/backlog", "CORE", "CORE-5", "in-progress",
                f"⏳ IN-PROGRESS ({stamp(500)}, T's session) — **WORKTREE PENDING.** Claim pushed; worktree not yet created.")
    write_issue(repo, "docs/backlog", "CORE", "CORE-6", "in-progress",
                f"⏳ IN-PROGRESS ({stamp(500)}, T's session) — **RESERVED, NOT STARTED.** Claimed as part of the slice, queued behind CORE-5.")
    cs = _claims(repo)
    assert cs["claim CORE-5"].status == ld.OK and "setting up" in cs["claim CORE-5"].detail
    assert cs["claim CORE-6"].status == ld.OK and "queued behind" in cs["claim CORE-6"].detail


def test_in_progress_without_marker_and_exempt(repo):
    write_issue(repo, "docs/backlog", "CORE", "CORE-7", "in-progress", "Working on it.")
    assert _claims(repo)["claim CORE-7"].status == ld.WARN
    assert "claim CORE-7" not in _claims(repo, exempt=["CORE-7"])


def test_date_only_marker_is_treated_as_live_with_a_note(repo):
    write_issue(repo, "docs/backlog", "CORE", "CORE-8", "in-progress",
                "⏳ IN-PROGRESS (2026-09-01, T's session) — **RESERVED, NOT STARTED.** queued.")
    c = _claims(repo)["claim CORE-8"]
    assert c.status == ld.OK and "age unknown" in c.detail


def test_closed_issues_are_ignored_and_index_skipped(repo):
    write_issue(repo, "docs/backlog", "CORE", "CORE-9", "closed", "done")
    (repo / "docs/backlog/INDEX.md").write_text("status: in-progress\n", encoding="utf-8")
    cs = _claims(repo)
    assert list(cs) == ["claims"] and cs["claims"].status == ld.OK


def test_json_and_text_output(repo, capsys):
    assert ld.main(["--root", str(repo), "--json"]) == 1
    import json
    data = json.loads(capsys.readouterr().out)
    assert {"status", "label", "detail"} <= set(data[0])
    ld.main(["--root", str(repo)])
    out = capsys.readouterr().out
    assert "FAIL  config" in out and "fail" in out.splitlines()[-1]
