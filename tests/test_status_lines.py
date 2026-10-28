"""status_lines.py: the startup checks' status lines fold into what the Brief shows (LANES-66).

The incident: on one project's Brief, 7 of 14 bullets were all-clear checks, and the one line
that had to be read came last. The fold keeps only what is not ok, worst first, and turns
every OK line into one name on a `health:` line.
"""
import subprocess
import sys
from pathlib import Path

import status_lines as sl

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "status_lines.py"


def test_parse_reads_the_level_the_name_and_the_detail():
    assert sl.parse("OK canary: last run GREEN at d62d4c7 (4939 passed)") == \
        ("OK", "canary", "last run GREEN at d62d4c7 (4939 passed)")
    assert sl.parse("CRITICAL nightly: RED 2026-10-27 at c634eb8 — windows failure at 'Collect'")[:2] == \
        ("CRITICAL", "nightly")
    assert sl.parse("CUE commit guard: re-pointed at .git/hooks/pre-commit")[1] == "commit guard"


def test_every_ok_line_collapses_into_one_health_line():
    lines = ["OK pull: up to date at c05a16d", "OK doctor: 18 ok, 0 warn, 0 fail",
             "OK canary: last run GREEN at d62d4c7", "OK canary: running at bd57a03"]
    assert sl.fold(lines) == ["health: all clear — pull · doctor · canary"]


def test_cue_and_critical_keep_their_own_lines_worst_first_before_health():
    lines = ["OK pull: up to date at c05a16d",
             "CUE slow machine: every file ~1.9x slower; two suites running",
             "CRITICAL nightly: RED 2026-10-27 at c634eb8",
             "OK corpus: 151 files match"]
    assert sl.fold(lines) == [
        "CRITICAL nightly: RED 2026-10-27 at c634eb8",
        "CUE slow machine: every file ~1.9x slower; two suites running",
        "health: 2 ok — pull · corpus",
    ]


def test_a_line_in_any_other_spelling_is_shown_in_full_never_folded():
    lines = ["OK pull: up to date at c05a16d",
             "[canary] last run 2026-10-27 23:25:31 UTC: GREEN at d62d4c7",   # not yet levelled
             "OK everything is fine",                                       # a level, but no name
             "ok corpus: 151 files match",                                  # the level is uppercase
             "OK a name that runs on far too long to be a check's name at all: x",
             ""]
    out = sl.fold(lines)
    assert out[:4] == lines[1:5]
    assert out[-1] == "health: 1 ok — pull"
    assert sl.parse(lines[2]) is None and sl.parse(lines[4]) is None


def test_nothing_ok_means_no_health_line_and_nothing_at_all_means_no_output():
    assert sl.fold(["CUE doctor: 1 warn"]) == ["CUE doctor: 1 warn"]
    assert sl.fold([]) == [] and sl.fold(["", "   "]) == []


def test_the_cli_reads_stdin_and_prints_the_fold():
    stdin = "OK pull: up to date\nCRITICAL backlog check: duplicate ID UI-114\nOK doctor: 0 warn, 0 fail\n"
    r = subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True,
                       text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["CRITICAL backlog check: duplicate ID UI-114",
                                     "health: 2 ok — pull · doctor"]
