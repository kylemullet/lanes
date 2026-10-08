"""release_tag.py: a release mints its tag, and a pin's tag can be looked up (LANES-33).

The incident: releases moved to `next` and nobody tagged them, so a consumer CI that
checks the plugin out at `lanes--v<pin>` failed on every push for twenty releases.
"""
import json

import pytest

import release_tag as rt
from conftest import git


def _plugin(tmp_path, version="1.2.3", subject="lanes 1.2.3 — a release"):
    """A bare origin and a plugin checkout whose HEAD carries `version`, pushed."""
    origin = tmp_path / "plugin.git"
    git("init", "-q", "--bare", "-b", "next", str(origin), cwd=tmp_path)
    co = tmp_path / "plugin"
    git("clone", "-q", str(origin), str(co), cwd=tmp_path)
    git("config", "user.email", "t@example.com", cwd=co)
    git("config", "user.name", "Tester", cwd=co)
    _release(co, version, subject)
    return origin, co


def _release(co, version, subject):
    (co / ".claude-plugin").mkdir(exist_ok=True)
    (co / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "lanes", "version": version}),
                                                       encoding="utf-8")
    git("add", ".claude-plugin/plugin.json", cwd=co)
    git("commit", "-q", "-m", subject, cwd=co)
    git("push", "-q", "origin", "HEAD:next", cwd=co)


def _remote_tags(origin, tmp_path):
    out = git("ls-remote", "--tags", str(origin), cwd=tmp_path)
    return {line.split("refs/tags/")[1] for line in out.splitlines() if not line.endswith("^{}")}


def test_ensure_push_tags_head_annotated_with_the_release_subject(tmp_path):
    origin, co = _plugin(tmp_path)
    status, line = rt.ensure(co, push=True)
    assert status == 0 and "tagged lanes--v1.2.3" in line and "pushed" in line
    assert _remote_tags(origin, tmp_path) == {"lanes--v1.2.3"}
    assert git("cat-file", "-t", "lanes--v1.2.3", cwd=co) == "tag"
    assert git("tag", "-l", "--format=%(contents:subject)", "lanes--v1.2.3", cwd=co) == "lanes 1.2.3 — a release"
    assert git("rev-parse", "lanes--v1.2.3^{commit}", cwd=co) == git("rev-parse", "HEAD", cwd=co)


def test_ensure_is_a_no_op_once_the_version_is_tagged(tmp_path):
    """A push that does not bump the version leaves the tag where the release put it."""
    origin, co = _plugin(tmp_path)
    rt.ensure(co, push=True)
    first = git("rev-parse", "lanes--v1.2.3^{commit}", cwd=co)
    (co / "README.md").write_text("docs\n", encoding="utf-8")
    git("add", "README.md", cwd=co)
    git("commit", "-q", "-m", "docs only", cwd=co)
    git("push", "-q", "origin", "HEAD:next", cwd=co)
    status, line = rt.ensure(co, push=True)
    assert status == 0 and "already on origin" in line
    out = git("ls-remote", "--tags", str(origin), "refs/tags/lanes--v1.2.3^{}", cwd=tmp_path)
    assert out.split()[0] == first


def test_ensure_tags_each_new_version(tmp_path):
    origin, co = _plugin(tmp_path)
    rt.ensure(co, push=True)
    _release(co, "1.2.4", "lanes 1.2.4 — the next one")
    assert rt.ensure(co, push=True)[0] == 0
    assert _remote_tags(origin, tmp_path) == {"lanes--v1.2.3", "lanes--v1.2.4"}


def test_ensure_without_push_leaves_the_remote_alone(tmp_path):
    origin, co = _plugin(tmp_path)
    status, line = rt.ensure(co, push=False)
    assert status == 0 and "not pushed" in line
    assert _remote_tags(origin, tmp_path) == set()
    assert rt.ensure(co, push=True)[0] == 0          # the local tag is pushed, not re-made
    assert _remote_tags(origin, tmp_path) == {"lanes--v1.2.3"}


def test_ensure_fails_when_the_remote_cannot_be_read(tmp_path):
    _origin, co = _plugin(tmp_path)
    status, line = rt.ensure(co, remote=str(tmp_path / "nowhere.git"), push=True)
    assert status == 1 and "cannot read tags" in line


@pytest.mark.parametrize("tagged", [True, False])
def test_tag_on_remote(tmp_path, monkeypatch, tagged):
    origin, co = _plugin(tmp_path)
    if tagged:
        rt.ensure(co, push=True)
    monkeypatch.setenv(rt.REMOTE_ENV, str(origin))
    assert rt.tag_on_remote("1.2.3") is tagged
    assert rt.tag_on_remote("1.2.30") is False       # a prefix is not a match


def test_tag_on_remote_is_none_when_off_or_unreachable(tmp_path, monkeypatch):
    assert rt.release_remote() is None               # conftest: set and empty
    assert rt.tag_on_remote("1.2.3") is None
    monkeypatch.setenv(rt.REMOTE_ENV, str(tmp_path / "nowhere.git"))
    assert rt.tag_on_remote("1.2.3") is None


def test_the_default_remote_is_the_manifest_repository(monkeypatch):
    monkeypatch.delenv(rt.REMOTE_ENV)
    assert rt.release_remote() == rt.manifest()["repository"]
    assert rt.tag_name("9.9.9") == "lanes--v9.9.9"


def test_cli_check_exit_status(tmp_path, monkeypatch, capsys):
    origin, co = _plugin(tmp_path)
    rt.ensure(co, push=True)
    monkeypatch.setenv(rt.REMOTE_ENV, str(origin))
    assert rt.main(["--check", "1.2.3"]) == 0
    assert rt.main(["--check", "1.2.4"]) == 1
    assert "is NOT on" in capsys.readouterr().out
    monkeypatch.setenv(rt.REMOTE_ENV, "")
    assert rt.main(["--check", "1.2.3"]) == 2
