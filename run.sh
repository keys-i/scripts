#!/bin/sh
set -eu

workspace=

cleanup() {
    if [ -n "$workspace" ] && [ -d "$workspace" ]; then
        rm -rf -- "$workspace"
    fi
}

run_launcher() {
    if [ ! -t 0 ] && [ -r /dev/tty ] && (: </dev/tty) 2>/dev/null; then
        "$@" </dev/tty
    else
        "$@"
    fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM

launcher_path=$0
case "$launcher_path" in
    */*) ;;
    *) launcher_path=./$launcher_path ;;
esac

if [ -f "$launcher_path" ]; then
    script_root=$(CDPATH= cd -- "$(dirname -- "$launcher_path")" && pwd -P)
else
    for tool in curl tar; do
        command -v "$tool" >/dev/null 2>&1 || {
            echo "run.sh: $tool is required for streamed use" >&2
            exit 127
        }
    done
    workspace=$(mktemp -d "${TMPDIR:-/tmp}/scripts.XXXXXX")
    curl -fsSL \
        "${SCRIPTS_ARCHIVE_URL:-https://github.com/keys-i/scripts/archive/refs/heads/main.tar.gz}" \
        -o "$workspace/source.tar.gz"
    tar -xzf "$workspace/source.tar.gz" --strip-components=1 -C "$workspace"
    if [ ! -f "$workspace/dev/run.py" ]; then
        echo "run.sh: downloaded source archive is invalid" >&2
        exit 127
    fi
    script_root=$workspace
fi

for python in python3 python; do
    if command -v "$python" >/dev/null 2>&1 &&
        "$python" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'
    then
        run_launcher "$python" "$script_root/dev/run.py" "$@"
        exit $?
    fi
done

if command -v uv >/dev/null 2>&1; then
    run_launcher uv run --python 3.11 "$script_root/dev/run.py" "$@"
    exit $?
fi

echo "run.sh: Python 3.11+ or uv is required" >&2
exit 127
