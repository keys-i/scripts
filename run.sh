#!/bin/sh
set -eu

script_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)

for python in python3 python; do
    if command -v "$python" >/dev/null 2>&1; then
        exec "$python" "$script_root/dev/run.py" "$@"
    fi
done

echo "run.sh: Python 3 is required" >&2
exit 127
