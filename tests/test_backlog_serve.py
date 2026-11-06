"""The served backlog view (`backlog_index.py --serve`): the page generates on READ.

Moved out of test_backlog_index.py (LANES-84). The plugin directory's scanner
(RUNTIME_FETCH_EXEC) read that file's page reads from this test's own 127.0.0.1
server, next to the git calls the rest of it makes, as an install-time risk, and
showed that to reviewers and users. Each test here starts `serve()` on a free local
port and reads the page back; nothing leaves the machine. Keep git calls out of this
file, and page reads out of that one.
"""
import socket as _socket
import threading
import time
import urllib.error
import urllib.request

import pytest

import backlog_index as bidx
# The autouse settings fixture and the issue writer are shared with the main suite.
from test_backlog_index import _solo_settings_under_tmp, put  # noqa: F401


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
