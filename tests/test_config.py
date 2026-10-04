import lanes_config as lc


def test_defaults_resolve_to_solo_mode():
    cfg = lc.resolve({}, user_name="Kyle Mullet", platform="darwin")
    assert cfg["solo"] is True
    assert cfg["machine"]["certifies"] is True and cfg["machine"]["may_edit_code"] is True
    assert cfg["machine"]["id"] == "Kyle Mullet+darwin"
    assert cfg["machine"]["short"] == "kyle-mullet"
    assert cfg["assignees"] == ["kyle-mullet", "shared"]
    assert cfg["reporters"] == ["claude", "kyle-mullet"]
    assert cfg["docs_lane_prefixes"] == cfg["main_direct_paths"] == ["docs/", ".claude/lanes/", "*.md"]
    assert cfg["main_branch"] == "main" and cfg["test_command"] == "pytest -q"
    assert cfg["rebase_rerun_command"] is None and cfg["port_command"] is None
    assert cfg["statuses"] == list(lc.STATUSES) and cfg["claim_age_floor_minutes"] == 15


def test_docs_lane_prefixes_override_is_independent_of_main_direct():
    raw = {"git": {"main_direct_paths": ["docs/", ".claude/skills/", "*.md"]},
           "backlog": {"docs_lane_prefixes": ["docs/", "*.md"]}}
    cfg = lc.resolve(raw, user_name="x", platform="linux")
    assert ".claude/skills/" in cfg["main_direct_paths"]
    assert ".claude/skills/" not in cfg["docs_lane_prefixes"]


TWO_OPS = {"operators": [
    {"name": "kylemullet", "platform": "darwin", "id": "kyle-mac", "short": "kyle", "certifies": True, "may_edit_code": True},
    {"name": "Mike", "platform": "win32", "id": "mike-win", "short": "mike", "certifies": False, "may_edit_code": False},
]}


def test_two_operator_machine_rows():
    assert lc.validate(TWO_OPS) == []
    kyle = lc.resolve(TWO_OPS, user_name="kylemullet", platform="darwin")
    assert kyle["solo"] is False and kyle["machine"]["id"] == "kyle-mac" and kyle["machine"]["certifies"]
    mike = lc.resolve(TWO_OPS, user_name="Mike", platform="win32")
    assert mike["machine"]["id"] == "mike-win" and not mike["machine"]["certifies"] and not mike["machine"]["may_edit_code"]
    assert mike["assignees"] == ["kyle", "mike", "shared"] and mike["reporters"] == ["claude", "kyle", "mike"]


def test_unknown_machine_in_multi_operator_repo_has_no_permissions():
    cfg = lc.resolve(TWO_OPS, user_name="kylemullet", platform="win32")
    m = cfg["machine"]
    assert m["known"] is False and m["certifies"] is False and m["may_edit_code"] is False
    assert m["id"] == "kylemullet+win32"


def _errors(raw):
    return [p.message for p in lc.validate(raw) if p.level == "error"]


def _warnings(raw):
    return [p.message for p in lc.validate(raw) if p.level == "warning"]


def test_types_must_include_epic():
    assert any("epic" in m for m in _errors({"backlog": {"types": ["story", "bug"]}}))


def test_statuses_and_resolutions_are_protocol_not_config():
    errs = _errors({"backlog": {"statuses": ["open"], "resolutions": ["done"]}})
    assert any("statuses" in m for m in errs) and any("resolutions" in m for m in errs)


def test_project_prefix_shape():
    assert _errors({"backlog": {"projects": ["pipe"]}})
    assert _errors({"backlog": {"projects": []}})
    assert _errors({"backlog": {"projects": ["A", "A"]}})
    assert not _errors({"backlog": {"projects": ["PIPE", "UI2"]}})


def test_operator_rules():
    dup = {"operators": [
        {"name": "a", "platform": "darwin", "id": "x", "short": "s"},
        {"name": "b", "platform": "darwin", "id": "x", "short": "s"},
    ]}
    errs = _errors(dup)
    assert any("duplicate operator id" in m for m in errs) and any("duplicate operator short" in m for m in errs)
    assert any("missing `short`" in m for m in _errors({"operators": [{"name": "a", "platform": "darwin", "id": "x"}]}))
    assert any("reserved" in m for m in _errors({"operators": [{"name": "a", "platform": "darwin", "id": "x", "short": "claude"}]}))
    assert any("certifies" in m for m in _warnings({"operators": [{"name": "a", "platform": "darwin", "id": "x", "short": "s"}]}))
    same_pair = {"operators": [
        {"name": "a", "platform": "darwin", "id": "x", "short": "s", "certifies": True},
        {"name": "a", "platform": "darwin", "id": "y", "short": "t"},
    ]}
    assert any("name+platform" in m for m in _errors(same_pair))


def test_lanes_table_rules():
    assert any("solo mode" in m for m in _warnings({"lanes": {"code": ["src/"]}}))
    raw = dict(TWO_OPS, lanes={"code": ["src/"], "code_owner": "nobody"})
    assert any("code_owner" in m for m in _errors(raw))
    raw = dict(TWO_OPS, lanes={"code": ["src/"], "code_owner": "kyle-mac"})
    assert not _errors(raw)


def test_type_and_unknown_key_checks():
    assert any("must be a str" in m for m in _errors({"git": {"main_branch": 3}}))
    assert any("list of strings" in m for m in _errors({"git": {"main_direct_paths": ["docs/", 7]}}))
    assert any("unknown key `git.foo`" in m for m in _warnings({"git": {"foo": 1}}))
    assert any("unknown top-level" in m for m in _warnings({"bogus": {}}))
    assert any("YYYY-MM-DD" in m for m in _errors({"backlog": {"resolution_required_from": "yesterday"}}))
    assert any("view_port" in m for m in _errors({"backlog": {"view_port": 80}}))
    assert any("MAJOR.MINOR.PATCH" in m for m in _warnings({"plugin_version": "v1"}))


def test_load_missing_and_broken(repo):
    loaded = lc.load(root=repo)
    assert loaded.found is False and loaded.problems == [] and loaded.raw == {}
    cfg_path = repo / lc.CONFIG_REL
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("this is = not toml [", encoding="utf-8")
    loaded = lc.load(root=repo)
    assert loaded.found and loaded.parse_error and loaded.errors


def test_repo_root_answers_from_subdir(repo):
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    assert lc.repo_root(cwd=sub) == repo


def test_installed_version_matches_manifest():
    import json
    manifest = lc.plugin_root() / ".claude-plugin" / "plugin.json"
    assert lc.installed_version() == json.loads(manifest.read_text())["version"]
