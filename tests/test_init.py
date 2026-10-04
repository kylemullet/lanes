import lanes_config as lc
import lanes_init as li
from conftest import git


def test_scaffold_writes_then_keeps_then_forces(repo):
    first = li.scaffold(repo, force=False, projects=["CORE", "INFRA"])
    assert sorted(first["wrote"]) == sorted([
        ".claude/lanes/config.toml", ".claude/lanes/preflight.md",
        ".claude/lanes/lane-setup.md", ".claude/lanes/pre-land.md"])
    assert first["kept"] == [] and first["warnings"] == []
    cfg_text = (repo / lc.CONFIG_REL).read_text(encoding="utf-8")
    assert f'plugin_version = "{lc.installed_version()}"' in cfg_text
    assert 'projects = ["CORE", "INFRA"]' in cfg_text
    assert "{{" not in cfg_text

    loaded = lc.load(root=repo)
    assert loaded.found and loaded.problems == []
    cfg = lc.resolve(loaded.raw, user_name="Tester", platform="linux")
    assert cfg["solo"] and cfg["projects"] == ["CORE", "INFRA"]

    (repo / lc.CONFIG_REL).write_text("# edited by hand\n", encoding="utf-8")
    second = li.scaffold(repo, force=False, projects=["CORE"])
    assert second["wrote"] == [] and len(second["kept"]) == 4
    assert (repo / lc.CONFIG_REL).read_text(encoding="utf-8") == "# edited by hand\n"

    third = li.scaffold(repo, force=True, projects=["CORE"])
    assert len(third["wrote"]) == 4
    assert 'projects = ["CORE"]' in (repo / lc.CONFIG_REL).read_text(encoding="utf-8")


def test_gitignored_config_is_warned(repo):
    (repo / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    out = li.scaffold(repo, force=False, projects=["CORE"])
    assert any("gitignored" in w for w in out["warnings"])


def test_parse_projects():
    assert li.parse_projects(None) == lc.DEFAULTS["backlog"]["projects"]
    assert li.parse_projects("core, infra") == ["CORE", "INFRA"]
    import pytest
    with pytest.raises(SystemExit):
        li.parse_projects("1bad")


def test_main_outside_a_repo(tmp_path, capsys):
    bare = tmp_path / "nowhere"
    bare.mkdir()
    assert li.main(["--root", str(bare)]) == 1
    assert "not inside a git repository" in capsys.readouterr().err


def test_main_end_to_end(repo, capsys):
    assert li.main(["--root", str(repo), "--projects", "APP"]) == 0
    out = capsys.readouterr().out
    assert "wrote  .claude/lanes/config.toml" in out and "solo mode" in out and "projects: APP" in out
    git("add", ".claude", cwd=repo)
    git("commit", "-q", "-m", "lanes init", cwd=repo)
