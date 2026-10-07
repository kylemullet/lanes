"""scripts/lanes.sh -- every script runs under a PROVEN Python 3.11+, or nothing runs (LANES-17).

On Windows `python3` can be the Microsoft Store alias: it prints an install hint and exits
49. A PreToolUse hook that exits anything but 2 lets the tool call through, so a hook that
named `python3` directly failed OPEN on such a machine. Each test builds a PATH holding
only the fakes it needs (plus `sh` and `dirname`), so the host's own interpreters can never
answer for the launcher.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "scripts" / "lanes.sh"

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("sh") is None,
    reason="builds fake interpreters as sh scripts on a POSIX PATH")

STORE_ALIAS = "#!/bin/sh\necho 'Python was not found; run without arguments to install from the Microsoft Store' >&2\nexit 49\n"
OLD_PYTHON = "#!/bin/sh\nexit 1\n"  # answers, but fails the 3.11 probe the way a 3.9 does


def _bin(tmp_path, **fakes):
    """A PATH directory with sh + dirname and the named fakes (a str body, or 'real')."""
    d = tmp_path / "bin"
    d.mkdir()
    for tool in ("sh", "dirname"):
        (d / tool).symlink_to(shutil.which(tool))
    for name, body in fakes.items():
        if body == "real":
            (d / name).symlink_to(sys.executable)
        else:
            (d / name).write_text(body, encoding="utf-8")
            (d / name).chmod(0o755)
    return d


def _plugin(tmp_path):
    """A copy of the launcher beside a probe script that reports what ran it."""
    d = tmp_path / "scripts"
    d.mkdir()
    shutil.copy(LAUNCHER, d / "lanes.sh")
    (d / "probe.py").write_text(
        "import sys\nprint('ran', *sys.argv[1:])\nsys.exit(int(sys.argv[1]) if sys.argv[1:] and sys.argv[1].isdigit() else 0)\n",
        encoding="utf-8")
    return d


def _run(bindir, launcher, *args, env=None, stdin=None):
    e = {"PATH": str(bindir)}
    e.update(env or {})
    return subprocess.run([shutil.which("sh"), str(launcher), *args], env=e, input=stdin,
                          capture_output=True, text=True, timeout=30)


def test_store_alias_alone_fails_closed(tmp_path):
    r = _run(_bin(tmp_path, python3=STORE_ALIAS), _plugin(tmp_path) / "lanes.sh", "probe.py")
    assert r.returncode == 2, "no working interpreter must BLOCK (exit 2), never allow"
    assert "ran" not in r.stdout
    assert "no working Python 3.11+" in r.stderr


def test_no_interpreter_at_all_fails_closed(tmp_path):
    r = _run(_bin(tmp_path), _plugin(tmp_path) / "lanes.sh", "probe.py")
    assert r.returncode == 2


def test_store_alias_is_skipped_for_a_real_python(tmp_path):
    r = _run(_bin(tmp_path, python3=STORE_ALIAS, python="real"), _plugin(tmp_path) / "lanes.sh",
             "probe.py", "a", "b c")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ran a b c"


def test_an_old_python_is_skipped_for_the_windows_launcher(tmp_path):
    r = _run(_bin(tmp_path, python3=OLD_PYTHON, python=OLD_PYTHON, py="real"),
             _plugin(tmp_path) / "lanes.sh", "probe.py")
    assert r.returncode == 0, r.stderr


def test_the_scripts_exit_status_passes_through(tmp_path):
    r = _run(_bin(tmp_path, python3="real"), _plugin(tmp_path) / "lanes.sh", "probe.py", "3")
    assert r.returncode == 3


def test_lanes_python_is_used_when_set(tmp_path):
    bindir = _bin(tmp_path, python3=STORE_ALIAS)
    r = _run(bindir, _plugin(tmp_path) / "lanes.sh", "probe.py", env={"LANES_PYTHON": sys.executable})
    assert r.returncode == 0, r.stderr


def test_a_broken_lanes_python_is_not_silently_replaced(tmp_path):
    bindir = _bin(tmp_path, python3="real", broken=STORE_ALIAS)
    r = _run(bindir, _plugin(tmp_path) / "lanes.sh", "probe.py", env={"LANES_PYTHON": str(bindir / "broken")})
    assert r.returncode == 2
    assert "LANES_PYTHON" in r.stderr


@pytest.mark.parametrize("name", ["../probe.py", "sub/probe.py", "", "missing.py", "probe.py;id"])
def test_only_a_script_in_its_own_directory_runs(tmp_path, name):
    r = _run(_bin(tmp_path, python3="real"), _plugin(tmp_path) / "lanes.sh", name)
    assert r.returncode == 2
    assert "ran" not in r.stdout


def test_the_real_hook_command_blocks_when_only_the_store_alias_answers(tmp_path):
    """The hook as shipped, against the real guard: an edit into the main clone is refused
    because nothing can run the guard -- the exact Windows failure, closed."""
    cmd = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    hook = cmd["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert hook == 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" guard_position.py || exit 2'
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "x.py")}})
    r = _run(_bin(tmp_path, python3=STORE_ALIAS), LAUNCHER, "guard_position.py", stdin=payload)
    assert r.returncode == 2


def test_nothing_shipped_names_python3_for_a_plugin_script():
    """Hooks, commands, skills and the README all go through the launcher."""
    pat = re.compile(r"python3?\s+\\?\"?\$\{CLAUDE_PLUGIN_ROOT\}")
    shipped = [ROOT / "hooks" / "hooks.json", ROOT / "README.md", *ROOT.glob("commands/*.md"),
               *ROOT.glob("skills/*/SKILL.md"), *ROOT.glob("skills/*/references/*.md")]
    hits = [f"{p.relative_to(ROOT)}:{i}" for p in shipped
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if pat.search(line)]
    assert not hits, hits


def test_the_same_hook_payload_is_allowed_once_a_real_python_answers(tmp_path):
    """Counterpart: a target outside any repo is allowed by the guard itself, so the exit 2
    above is the launcher refusing, not the guard's verdict."""
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "x.py")}})
    bindir = _bin(tmp_path, python3=STORE_ALIAS, python="real")
    (bindir / "git").symlink_to(shutil.which("git"))  # the guard asks git where the target sits
    r = _run(bindir, LAUNCHER, "guard_position.py", stdin=payload)
    assert r.returncode == 0, r.stderr


def test_the_hook_command_blocks_when_the_launcher_itself_cannot_run(tmp_path):
    """`|| exit 2`: no launcher, no sh, or a guard that crashes all exit non-2, and every
    non-2 exit of a PreToolUse hook allows the write. The hook turns each into a block."""
    cmd = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    hook = cmd["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    empty = tmp_path / "plugin"
    (empty / "scripts").mkdir(parents=True)  # no lanes.sh: sh exits 127
    r = subprocess.run([shutil.which("sh"), "-c", hook], env={"PATH": os.environ["PATH"], "CLAUDE_PLUGIN_ROOT": str(empty)},
                       input="{}", capture_output=True, text=True, timeout=30)
    assert r.returncode == 2
