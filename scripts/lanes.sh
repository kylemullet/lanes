#!/bin/sh
# Run one of this directory's scripts under a working Python 3.11+.
#
#   sh "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.sh" <script.py> [args...]
#
# Every hook, command and skill goes through here instead of naming `python3`
# (LANES-17). On Windows `python3` can be the Microsoft Store alias: it prints an
# install hint and exits 49, and for a PreToolUse hook any exit but 2 ALLOWS the
# tool call -- the position guard failed open. So each candidate must prove it
# is a real 3.11+ (the scripts need `tomllib`) before it runs anything, and when
# none does, this exits 2: a guard that cannot run refuses, it never waves through.
#
# Candidates, in order: $LANES_PYTHON (this machine's explicit choice -- if set
# it must work, nothing is substituted for it), python3, python, py (the Windows
# launcher). The interpreter is per machine, so it is an environment variable,
# never a key in the repo's config.

if [ $# -lt 1 ]; then
    echo "usage: sh lanes.sh <script.py> [args...]" >&2
    exit 2
fi
script=$1
shift
case $script in
    "" | *[!A-Za-z0-9_.]* )
        echo "lanes: '$script' is not a script in the plugin's scripts/ directory" >&2
        exit 2 ;;
esac
here=$(dirname "$0")
if [ ! -f "$here/$script" ]; then
    echo "lanes: no such script: $here/$script" >&2
    exit 2
fi

works() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

if [ -n "${LANES_PYTHON:-}" ]; then
    if works "$LANES_PYTHON"; then
        exec "$LANES_PYTHON" "$here/$script" "$@"
    fi
    echo "lanes: LANES_PYTHON='$LANES_PYTHON' is not a working Python 3.11+ -- fix it or unset it" >&2
    exit 2
fi

for py in python3 python py; do
    if command -v "$py" >/dev/null 2>&1 && works "$py"; then
        exec "$py" "$here/$script" "$@"
    fi
done

echo "lanes: no working Python 3.11+ found (tried python3, python, py; a Microsoft Store" >&2
echo "alias does not count). Install Python 3.11+, or set LANES_PYTHON to its path." >&2
exit 2
