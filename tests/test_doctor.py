from datetime import datetime, timedelta

import pytest

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


def test_views_must_be_gitignored(repo):
    (repo / "docs" / "backlog" / "CORE").mkdir(parents=True)
    cfg = lc.resolve({}, user_name="t", platform="linux")
    checks = {c.label: c for c in ld.check_backlog(repo, cfg)}
    assert checks["views"].status == ld.WARN and "INDEX.md" in checks["views"].detail
    (repo / ".gitignore").write_text("docs/backlog/INDEX.md\ndocs/backlog/index.html\n", encoding="utf-8")
    checks = {c.label: c for c in ld.check_backlog(repo, cfg)}
    assert checks["views"].status == ld.OK


SETTINGS = {
    "extraKnownMarketplaces": {"lanes-marketplace": {"source": {"source": "github", "repo": "o/lanes", "ref": "next"}}},
    "enabledPlugins": {"lanes@lanes-marketplace": True},
}


def _settings(repo, data, commit=True):
    import json
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / ".claude" / "settings.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    if commit:
        git("add", ".claude/settings.json", cwd=repo)
        git("commit", "-q", "-m", "settings", cwd=repo)


def _register(plugins, source, sha=None, clone_tip=None, tmp_path=None):
    """A fake ~/.claude/plugins: known_marketplaces.json (+ a marketplace clone and
    installed_plugins.json when a sha is given)."""
    import json
    entry = {"source": source}
    if clone_tip is not None:
        clone = tmp_path / "mkt-clone"
        clone.mkdir()
        git("init", "-q", cwd=clone)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x", cwd=clone)
        entry["installLocation"] = str(clone)
        clone_tip = git("rev-parse", "HEAD", cwd=clone)
    (plugins / "known_marketplaces.json").write_text(json.dumps({"lanes-marketplace": entry}), encoding="utf-8")
    if sha is not None:
        sha = clone_tip if sha == "tip" else sha
        rows = {"plugins": {"lanes@lanes-marketplace": [{"scope": "user", "version": "9", "gitCommitSha": sha}]}}
        (plugins / "installed_plugins.json").write_text(json.dumps(rows), encoding="utf-8")


def _plugins(monkeypatch, tmp_path):
    d = tmp_path / "plugins-dir"
    d.mkdir()
    monkeypatch.setenv("LANES_PLUGINS_DIR", str(d))
    return d


def test_settings_pin_detected(repo, monkeypatch, tmp_path):
    _register(_plugins(monkeypatch, tmp_path), {"source": "github", "repo": "o/lanes", "ref": "next"})
    _settings(repo, SETTINGS)
    checks = by_label(ld.check_settings(repo))
    assert [checks[k].status for k in ("settings", "settings lanes", "marketplace")] == [ld.OK, ld.OK, ld.OK]


def test_settings_modified_in_the_working_tree_warns_whatever_the_edit(repo, monkeypatch, tmp_path):
    _register(_plugins(monkeypatch, tmp_path), {"source": "github", "repo": "o/lanes", "ref": "next"})
    _settings(repo, SETTINGS)
    partial = {**SETTINGS, "extraKnownMarketplaces": {"lanes-marketplace": {"source": {"source": "github", "repo": "o/lanes"}}}}
    _settings(repo, partial, commit=False)          # still enables lanes — the old check passed it
    checks = by_label(ld.check_settings(repo))
    assert checks["settings"].status == ld.WARN and "git checkout --" in checks["settings"].detail
    assert checks["settings lanes"].status == ld.OK
    _settings(repo, {"extraKnownMarketplaces": {}, "enabledPlugins": {}}, commit=False)   # what `remove` leaves
    checks = by_label(ld.check_settings(repo))
    assert checks["settings"].status == ld.WARN
    assert checks["settings lanes"].status == ld.WARN and "working tree" in checks["settings lanes"].detail
    assert "committed" not in checks["settings lanes"].detail


def test_settings_committed_without_lanes_is_reported_as_committed(repo):
    _settings(repo, {"extraKnownMarketplaces": {}, "enabledPlugins": {}})
    checks = by_label(ld.check_settings(repo))
    assert checks["settings"].status == ld.OK                      # matches HEAD — the regression is committed
    lanes = checks["settings lanes"]
    assert lanes.status == ld.WARN and "committed (HEAD)" in lanes.detail and "fresh clone" in lanes.detail
    assert checks["marketplace"].status == ld.SKIP


def test_settings_enabled_without_its_marketplace_declared_warns(repo):
    _settings(repo, {"enabledPlugins": {"lanes@lanes-marketplace": True}})
    assert "extraKnownMarketplaces" in by_label(ld.check_settings(repo))["settings lanes"].detail


def test_marketplace_ref_mismatch_is_flagged(repo, monkeypatch, tmp_path):
    _register(_plugins(monkeypatch, tmp_path), {"source": "github", "repo": "o/lanes"})   # LANES-15: stale main
    _settings(repo, SETTINGS)
    mk = by_label(ld.check_settings(repo))["marketplace"]
    assert mk.status == ld.WARN and "ref `next`" in mk.detail and "(default branch)" in mk.detail


def test_marketplace_not_registered_on_this_machine(repo, monkeypatch, tmp_path):
    _plugins(monkeypatch, tmp_path)
    _settings(repo, SETTINGS)
    mk = by_label(ld.check_settings(repo))["marketplace"]
    assert mk.status == ld.WARN and "marketplace add o/lanes@next" in mk.detail


def test_installed_commit_behind_the_marketplace_clone(repo, monkeypatch, tmp_path):
    plugins = _plugins(monkeypatch, tmp_path)
    src = {"source": "github", "repo": "o/lanes", "ref": "next"}
    _register(plugins, src, sha="0" * 40, clone_tip=True, tmp_path=tmp_path)
    _settings(repo, SETTINGS)
    mk = by_label(ld.check_settings(repo))["marketplace"]
    assert mk.status == ld.WARN and "plugin update" in mk.detail
    (plugins / "installed_plugins.json").unlink()
    (tmp_path / "mkt-clone").rename(tmp_path / "old-clone")
    _register(plugins, src, sha="tip", clone_tip=True, tmp_path=tmp_path)
    mk = by_label(ld.check_settings(repo))["marketplace"]
    assert mk.status == ld.OK and "installed at its tip" in mk.detail


def test_plugins_dir_seam_order(monkeypatch, tmp_path):
    monkeypatch.setenv("LANES_PLUGINS_DIR", str(tmp_path / "x"))
    assert ld.plugins_dir() == tmp_path / "x"
    monkeypatch.delenv("LANES_PLUGINS_DIR")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert ld.plugins_dir() == tmp_path / "cfg" / "plugins"          # a dev checkout is not under cache/
    monkeypatch.setattr(lc, "plugin_root", lambda: tmp_path / "p" / "cache" / "m" / "lanes" / "1.0")
    assert ld.plugins_dir() == tmp_path / "p"


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


def test_a_claim_names_its_epic(repo):
    """LANES-31: the epic reads in progress through this claim, so the claim line says which."""
    p = write_issue(repo, "docs/backlog", "CORE", "CORE-3", "in-progress",
                    f"⏳ IN-PROGRESS ({stamp(3)}, T's session, worktree w, branch b) — **ACTIVE LANE.** x")
    p.write_text(p.read_text(encoding="utf-8").replace("status: in-progress\n", "status: in-progress\nepic: CORE-9\n"),
                 encoding="utf-8")
    assert _claims(repo)["claim CORE-3"].detail.endswith(" · epic CORE-9")


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


# --- paraphrased and kind-less markers (LANES-19) ----------------------------

@pytest.mark.parametrize("span, kind", [
    ("**ACTIVE LANE — readlines leg.**", "ACTIVE LANE"),
    ("**RESERVED, NOT STARTED — queued behind LANES-3**", "RESERVED"),
    ("**WORKTREE PENDING**", "WORKTREE PENDING"),
])
def test_a_paraphrased_kind_is_read_like_the_template(repo, span, kind):
    git("branch", "core-5-work", cwd=repo)
    write_issue(repo, "docs/backlog", "CORE", "CORE-5", "in-progress",
                f"⏳ IN-PROGRESS ({stamp(90)}, T's session, worktree proj-core-5, branch core-5-work) — {span} x")
    c = _claims(repo)["claim CORE-5"]
    assert c.status == ld.OK and c.detail.startswith(kind)


@pytest.mark.parametrize("minutes", [2, 90])
def test_a_kind_less_marker_warns_at_any_age(repo, minutes):
    write_issue(repo, "docs/backlog", "CORE", "CORE-6", "in-progress",
                f"⏳ IN-PROGRESS ({stamp(minutes)}, T's session) — **ACTIVE, readlines leg.** x")
    c = _claims(repo)["claim CORE-6"]
    assert c.status == ld.WARN and "no PENDING / RESERVED / ACTIVE kind" in c.detail


def test_a_nested_parenthesis_marker_is_read_alike_by_the_doctor_and_the_view(repo):
    """LANES-37: one string, one reading."""
    import backlog_index as bidx
    mk = (f"⏳ IN-PROGRESS ({stamp(3)}, T's session on t-box@host, worktree proj-core-7 + lanes-core-7 "
          "(lanes repo, off origin/next), branch core-7-work) — **ACTIVE LANE.** Expected files: x")
    write_issue(repo, "docs/backlog", "CORE", "CORE-7", "in-progress", mk)
    c = _claims(repo)["claim CORE-7"]
    assert c.status == ld.OK and c.detail.startswith("ACTIVE LANE")
    assert bidx.parse_marker(mk)["state"] == "active"


def test_a_marker_the_view_cannot_read_warns_even_when_the_doctor_can_classify_it(repo):
    """The doctor's lenient kind read must not report a lane the view does not show."""
    write_issue(repo, "docs/backlog", "CORE", "CORE-8", "in-progress",
                f"⏳ IN-PROGRESS ({stamp(3)}, T's session) — **ACTIVE LANE, readlines leg.** x — see [[CORE-1]]")
    c = _claims(repo)["claim CORE-8"]
    assert c.status == ld.OK, "sanity: this paraphrase IS readable by both"
    write_issue(repo, "docs/backlog", "CORE", "CORE-9", "in-progress",
                f"⏳ IN-PROGRESS ({stamp(3)}, T's session) **ACTIVE LANE.** no dash between header and kind")
    c = _claims(repo)["claim CORE-9"]
    assert c.status == ld.WARN and "the view cannot read the marker" in c.detail


# --- every install scope, not one (LANES-25) -------------------------------------------

def _installs(plugins, rows):
    import json
    (plugins / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {"lanes@lanes-marketplace": rows}}), encoding="utf-8")


def _pinned(repo, version):
    p = repo / lc.CONFIG_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'plugin_version = "{version}"\n', encoding="utf-8")
    return lc.resolve(lc.load(root=repo).raw, user_name="t", platform="linux")


def test_a_stale_user_scope_warns_even_when_the_project_scope_is_current(repo, monkeypatch, tmp_path):
    """The LANES-7 shape: `plugin update` moved only the project scope, and the session
    loaded the user scope's older copy while the doctor read 0 warn."""
    plugins = _plugins(monkeypatch, tmp_path)
    old, new = tmp_path / "cache" / "0.4.21", tmp_path / "cache" / "0.4.22"
    _installs(plugins, [
        {"scope": "user", "installPath": str(old), "version": "0.4.21", "gitCommitSha": "c" * 40},
        {"scope": "project", "projectPath": str(repo), "installPath": str(new), "version": "0.4.22",
         "gitCommitSha": "4" * 40},
        {"scope": "project", "projectPath": str(tmp_path / "elsewhere"), "version": "0.1.0"},   # another repo
    ])
    monkeypatch.setattr(lc, "plugin_root", lambda: old)
    monkeypatch.setattr(lc, "installed_version", lambda: "0.4.21")
    v = ld.check_version(_pinned(repo, "0.4.22"), repo)
    assert v.status == ld.WARN
    assert "user install is 0.4.21" in v.detail and "project install" not in v.detail
    assert "`claude plugin update lanes@lanes-marketplace --scope user`" in v.detail
    assert "this session runs the user install" in v.detail
    assert "0.1.0" not in v.detail, "a project install for another repo does not apply"


def test_every_scope_current_reads_ok_and_names_them(repo, monkeypatch, tmp_path):
    plugins = _plugins(monkeypatch, tmp_path)
    here = tmp_path / "cache" / "0.4.22"
    _installs(plugins, [{"scope": "user", "installPath": str(here), "version": "0.4.22"},
                        {"scope": "project", "projectPath": str(repo), "installPath": str(here), "version": "0.4.22"}])
    monkeypatch.setattr(lc, "plugin_root", lambda: here)
    monkeypatch.setattr(lc, "installed_version", lambda: "0.4.22")
    v = ld.check_version(_pinned(repo, "0.4.22"), repo)
    assert v.status == ld.OK and v.detail.endswith("(user + project)")


def test_a_worktree_session_uses_the_main_clones_project_install(repo, monkeypatch, tmp_path):
    plugins = _plugins(monkeypatch, tmp_path)
    lane = tmp_path / "proj-lane"
    git("worktree", "add", "-q", str(lane), "-b", "lane-work", cwd=repo)
    _installs(plugins, [{"scope": "project", "projectPath": str(repo), "version": "0.0.1"}])
    assert [r["version"] for _k, r in ld.lanes_installs(lane)] == ["0.0.1"]


def test_marketplace_names_each_scope_behind_the_clone(repo, monkeypatch, tmp_path):
    plugins = _plugins(monkeypatch, tmp_path)
    src = {"source": "github", "repo": "o/lanes", "ref": "next"}
    _register(plugins, src, clone_tip=True, tmp_path=tmp_path)
    tip = git("rev-parse", "HEAD", cwd=tmp_path / "mkt-clone")
    _installs(plugins, [{"scope": "user", "version": "9", "gitCommitSha": "0" * 40},
                        {"scope": "project", "projectPath": str(repo), "version": "9", "gitCommitSha": tip}])
    _settings(repo, SETTINGS)
    mk = by_label(ld.check_settings(repo))["marketplace"]
    assert mk.status == ld.WARN and "0000000 (user)" in mk.detail and "(project)" not in mk.detail
    assert "--scope user" in mk.detail


# --- the pinned version's release tag (LANES-33) ----------------------------

@pytest.fixture
def plugin_remote(tmp_path, monkeypatch):
    """A bare repo standing in for the plugin's remote, carrying `lanes--v1.0.0` only."""
    remote = tmp_path / "plugin.git"
    git("init", "-q", "--bare", "-b", "next", str(remote), cwd=tmp_path)
    seed = tmp_path / "seed"
    git("clone", "-q", str(remote), str(seed), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=seed)
    git("config", "user.name", "Tester", cwd=seed)
    git("commit", "-q", "--allow-empty", "-m", "lanes 1.0.0", cwd=seed)
    git("tag", "-a", "lanes--v1.0.0", "-m", "lanes 1.0.0", cwd=seed)
    git("push", "-q", "origin", "HEAD:next", "refs/tags/lanes--v1.0.0", cwd=seed)
    monkeypatch.setenv("LANES_RELEASE_REMOTE", str(remote))
    return remote


def test_release_tag_ok_when_the_pin_is_tagged(plugin_remote):
    c = ld.check_release_tag({"plugin_version": "1.0.0"})
    assert c.status == ld.OK and "lanes--v1.0.0 is on" in c.detail


def test_release_tag_warns_on_an_untagged_pin(plugin_remote):
    c = ld.check_release_tag({"plugin_version": "1.0.1"})
    assert c.status == ld.WARN and "lanes--v1.0.1 is not on" in c.detail and "--ensure --push" in c.detail


def test_release_tag_skips_offline_off_or_unpinned(tmp_path, monkeypatch):
    assert ld.check_release_tag({"plugin_version": None}).status == ld.SKIP
    assert "lookup off" in ld.check_release_tag({"plugin_version": "1.0.0"}).detail      # conftest: empty
    monkeypatch.setenv("LANES_RELEASE_REMOTE", str(tmp_path / "nowhere.git"))
    c = ld.check_release_tag({"plugin_version": "1.0.0"})
    assert c.status == ld.SKIP and "could not ask" in c.detail


def test_release_tag_is_one_of_the_run_checks(repo):
    assert "release tag" in by_label(ld.run(repo, now=NOW))
