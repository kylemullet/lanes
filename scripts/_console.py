"""Console-encoding guard for the plugin's CLI scripts.

A script that prints a `→`, a `⛔` or an em dash dies on Windows outside a UTF-8
console: PowerShell decodes as cp1252 and a redirected pipe as cp437, and neither
codepage has those characters. The failure is nastier than a cosmetic one because
the print is usually the LAST thing a script does, so the work has fully succeeded
while the exit status says otherwise.

Call `use_utf8_console()` as the first statement of `main()`. It is a no-op on
POSIX, where stdout is already UTF-8, and it never raises: a stream that cannot be
reconfigured (a test harness's capture object, a detached handle) is left as it was.

Stdlib-only, by design: the scripts run on machines with no virtualenv.
"""
import sys

__all__ = ["use_utf8_console"]


def use_utf8_console(streams=None):
    """Force stdout/stderr to UTF-8 with replacement, where the stream allows it.

    Returns the streams actually reconfigured, so a caller can tell "reconfigured"
    from "left alone".
    """
    if streams is None:
        streams = (sys.stdout, sys.stderr)
    done = []
    for stream in streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            continue
        done.append(stream)
    return tuple(done)
