"""Fold the startup checks' status lines into what the Brief shows (LANES-66).

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage:
  python3 status_lines.py < lines.txt     # every status line the startup checks printed, one per line

The contract. A check that reports into the Brief -- a step in `preflight.md`, or one of the
protocol's own -- prints each status line as

  <LEVEL> <name>: <detail>

with LEVEL one of `OK`, `CUE` or `CRITICAL`, and a short name with no colon in it (`canary`,
`commit guard`). `OK` means nothing to read; `CUE` is worth a glance and is never a finding;
`CRITICAL` goes on the Brief's `critical:` line, whatever mode the operator picks.

Why. The Brief is read at every startup, and most of what the checks print says nothing
changed: on one project's Brief, 7 of 14 bullets were all-clear, and the one line that had
to be read was last. So the fold shows only what is not ok, worst first, and every `OK`
line becomes one name on a single `health:` line.

A line that does not match the contract is shown in full, after the levelled ones: an
unmarked check can never be folded out of sight. Blank lines are dropped.
"""
from __future__ import annotations

import argparse, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402

LEVELS = ("CRITICAL", "CUE", "OK")   # worst first: the order the fold prints them in
LINE_RE = re.compile(r"^(OK|CUE|CRITICAL) ([^:\s][^:]{0,39}): (\S.*)$")


def parse(line: str):
    """(level, name, detail) for a line that follows the contract, else None."""
    m = LINE_RE.match(line.strip())
    return (m.group(1), m.group(2).strip(), m.group(3).strip()) if m else None


def fold(lines) -> list[str]:
    """The Brief's status lines: every CRITICAL, then every CUE, then every unmarked line,
    each as written; then one `health:` line naming the OK checks, or none if there are none."""
    shown = {level: [] for level in LEVELS}
    unmarked, ok_names = [], []
    for raw in lines:
        line = raw.rstrip("\n").strip()
        if not line:
            continue
        p = parse(line)
        if p is None:
            unmarked.append(line)
        elif p[0] == "OK":
            if p[1] not in ok_names:
                ok_names.append(p[1])
        else:
            shown[p[0]].append(line)
    out = shown["CRITICAL"] + shown["CUE"] + unmarked
    if ok_names:
        head = "all clear" if not out else f"{len(ok_names)} ok"
        out.append(f"health: {head} — {' · '.join(ok_names)}")
    return out


def main(argv=None) -> int:
    use_utf8_console()
    use_utf8_console((sys.stdin,))   # a heredoc of status lines carries em dashes too
    argparse.ArgumentParser(
        description="lanes: fold the startup checks' status lines (stdin) into the Brief's",
        epilog="Each line: `OK|CUE|CRITICAL <name>: <detail>`; anything else is shown in full.",
    ).parse_args(argv)
    for line in fold(sys.stdin):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
