"""OS-aware launcher for commands documented by adjacent .man files."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

SEARCH_DIRS = ("bin", "dev", "sys")
MAN_SUFFIX = ".man"
SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
SCRIPT_SUFFIXES = {".bat", ".cmd", ".ps1", ".py", ".sh"}


class LauncherError(Exception):
    """A concise launcher error."""


def host_os() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise LauncherError(f"unsupported operating system: {sys.platform}")


def metadata(help_path: Path) -> dict[str, object]:
    if help_path.is_symlink() or help_path.stat().st_size > 1024 * 1024:
        raise LauncherError(f"unsafe help page: {help_path}")
    text = help_path.read_text(encoding="utf-8")
    marker = text.find("\n---\n", 4)
    if not text.startswith("---\n") or marker < 0:
        raise LauncherError(f"invalid help front matter: {help_path}")
    try:
        value = json.loads(text[4:marker])
    except json.JSONDecodeError as error:
        raise LauncherError(f"invalid help JSON in {help_path}: {error}") from error
    if not isinstance(value, dict):
        raise LauncherError(f"help metadata is not an object: {help_path}")
    return value


def catalog(root: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for directory in SEARCH_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for help_path in sorted(base.rglob(f"*{MAN_SUFFIX}")):
            value = metadata(help_path)
            platform = value.get("platform")
            summary = value.get("summary")
            launchable = value.get("launchable", True)
            if platform not in {"any", "linux", "macos", "windows"}:
                raise LauncherError(f"invalid platform in {help_path}")
            if not isinstance(summary, str) or not summary.strip():
                raise LauncherError(f"missing summary in {help_path}")
            if not isinstance(launchable, bool):
                raise LauncherError(f"invalid launchable value in {help_path}")
            script = Path(str(help_path)[: -len(MAN_SUFFIX)])
            if script.is_symlink() or not script.is_file():
                raise LauncherError(f"unsafe or missing script for {help_path}")
            script_id = script.relative_to(root).as_posix()
            alias = (
                script.stem if script.suffix.lower() in SCRIPT_SUFFIXES else script.name
            )
            entries.append(
                {
                    "id": script_id,
                    "alias": alias,
                    "path": script,
                    "platform": platform,
                    "summary": summary.strip(),
                    "launchable": launchable,
                }
            )
    return entries


def compatible(
    entries: list[dict[str, object]], platform: str
) -> list[dict[str, object]]:
    return [
        entry
        for entry in entries
        if entry["launchable"] and entry["platform"] in {"any", platform}
    ]


def resolve(
    entries: list[dict[str, object]],
    platform: str,
    name: str,
) -> dict[str, object]:
    if not SAFE_NAME.fullmatch(name) or ".." in Path(name).parts:
        raise LauncherError(f"invalid script name: {name}")
    usable = compatible(entries, platform)
    exact = [entry for entry in usable if entry["id"] == name]
    if exact:
        return exact[0]
    aliases = [entry for entry in usable if entry["alias"] == name]
    if len(aliases) == 1:
        return aliases[0]
    if len(aliases) > 1:
        choices = ", ".join(str(entry["id"]) for entry in aliases)
        raise LauncherError(f"ambiguous script name {name!r}; use one of: {choices}")
    incompatible = [entry for entry in entries if entry["id"] == name]
    if incompatible:
        raise LauncherError(f"{name} is not available on {platform}")
    raise LauncherError(f"unknown script: {name}; run './run.sh list'")


def show(entries: list[dict[str, object]], platform: str) -> None:
    usable = compatible(entries, platform)
    counts = {
        alias: sum(entry["alias"] == alias for entry in usable)
        for alias in {str(entry["alias"]) for entry in usable}
    }
    rows = [
        (
            str(entry["alias"])
            if counts[str(entry["alias"])] == 1
            else str(entry["id"]),
            str(entry["id"]),
            str(entry["summary"]),
        )
        for entry in usable
    ]
    width = max((len(row[0]) for row in rows), default=4)
    print(f"Usable scripts on {platform}:\n")
    for name, script_id, summary in rows:
        location = "" if name == script_id else f"  [{script_id}]"
        print(f"  {name:<{width}}{location}\n    {summary}")


def launch(entry: dict[str, object], arguments: list[str]) -> None:
    script = Path(str(entry["path"]))
    suffix = script.suffix.lower()
    if suffix == ".ps1":
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            raise LauncherError("PowerShell is required for this script")
        command = [powershell, "-NoLogo", "-NoProfile", "-File", str(script)]
    elif suffix in {".bat", ".cmd"}:
        command = ["cmd.exe", "/d", "/c", str(script)]
    elif suffix == ".sh":
        shell = shutil.which("bash") or shutil.which("sh")
        if not shell:
            raise LauncherError("a POSIX shell is required for this script")
        command = [shell, str(script)]
    else:
        with script.open(encoding="utf-8", errors="replace") as handle:
            first_line = handle.readline()
        if "uv run" in first_line:
            uv = shutil.which("uv")
            if not uv:
                raise LauncherError("uv is required for this Python script")
            command = [uv, "run", "--script", str(script)]
        elif suffix == ".py":
            command = [sys.executable, str(script)]
        else:
            command = [str(script)]
    os.execvp(command[0], [*command, *arguments])


def self_test(root: Path, entries: list[dict[str, object]]) -> None:
    for platform in ("linux", "macos", "windows"):
        assert compatible(entries, platform)
        assert resolve(entries, platform, "security-audit")["platform"] == "any"
        assert resolve(entries, platform, "clean")["platform"] == platform
    assert all(entry["id"] != "dev/gui.py" for entry in compatible(entries, host_os()))
    print(f"ok: {len(entries)} documented scripts and three OS catalogs")


def main(arguments: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        entries = catalog(root)
        platform = host_os()
        if arguments in ([], ["--help"], ["-h"]):
            print("Usage: ./run.sh <list|script_name> [arguments...]")
            return 0
        if arguments == ["--self-test"]:
            self_test(root, entries)
            return 0
        if arguments == ["list"]:
            show(entries, platform)
            return 0
        if arguments[0] == "list":
            raise LauncherError("list does not accept arguments")
        launch(resolve(entries, platform, arguments[0]), arguments[1:])
        return 0
    except (LauncherError, OSError, UnicodeError) as error:
        print(f"run.sh: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
