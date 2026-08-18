"""OS-aware launcher for commands documented by adjacent .man files."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from _manual import PRIVILEGE_LABELS

SEARCH_DIRS = ("bin", "dev", "sys", "packs")
MAN_SUFFIX = ".man"
SAFE_NAME = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
COMMAND_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
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
        raise LauncherError(f"unsafe manual: {help_path}")
    text = help_path.read_text(encoding="utf-8")
    marker = text.find("\n---\n", 4)
    if not text.startswith("---\n") or marker < 0:
        raise LauncherError(f"invalid manual front matter: {help_path}")
    try:
        value = json.loads(text[4:marker])
    except json.JSONDecodeError as error:
        raise LauncherError(f"invalid manual JSON in {help_path}: {error}") from error
    if not isinstance(value, dict):
        raise LauncherError(f"manual metadata is not an object: {help_path}")
    return value


def catalog(root: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    help_paths = [root / "run.sh.man"]
    for directory in SEARCH_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        help_paths.extend(base.rglob(f"*{MAN_SUFFIX}"))
    for help_path in sorted(help_paths):
        value = metadata(help_path)
        platform = value.get("platform")
        summary = value.get("summary")
        privilege = value.get("privilege")
        apply_flag = value.get("applyFlag")
        launchable = value.get("launchable", True)
        executable = value.get("executable")
        if platform not in {"any", "linux", "macos", "windows"}:
            raise LauncherError(f"invalid platform in {help_path}")
        if not isinstance(summary, str) or not summary.strip():
            raise LauncherError(f"missing summary in {help_path}")
        if privilege not in PRIVILEGE_LABELS:
            raise LauncherError(f"invalid privilege in {help_path}")
        if apply_flag is not None and (
            not isinstance(apply_flag, str) or not apply_flag.startswith("-")
        ):
            raise LauncherError(f"invalid apply flag in {help_path}")
        if not isinstance(launchable, bool):
            raise LauncherError(f"invalid launchable value in {help_path}")
        if executable is not None and (
            not isinstance(executable, str) or not COMMAND_NAME.fullmatch(executable)
        ):
            raise LauncherError(f"invalid executable in {help_path}")
        adjacent = Path(str(help_path)[: -len(MAN_SUFFIX)])
        if executable is None:
            if adjacent.is_symlink() or not adjacent.is_file():
                raise LauncherError(f"unsafe or missing script for {help_path}")
            script = adjacent
            script_id = script.relative_to(root).as_posix()
        else:
            script = Path(executable)
            script_id = adjacent.relative_to(root).as_posix()
        alias = script.stem if script.suffix.lower() in SCRIPT_SUFFIXES else script.name
        entries.append(
            {
                "id": script_id,
                "alias": alias,
                "path": script,
                "external": executable is not None,
                "manual": help_path,
                "platform": platform,
                "privilege": privilege,
                "apply_flag": apply_flag,
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
    *,
    runnable: bool = True,
) -> dict[str, object]:
    if not SAFE_NAME.fullmatch(name) or ".." in Path(name).parts:
        raise LauncherError(f"invalid script name: {name}")
    usable = compatible(entries, platform) if runnable else entries
    exact = [entry for entry in usable if entry["id"] == name]
    if exact:
        return exact[0]
    aliases = [entry for entry in usable if entry["alias"] == name]
    if not runnable and len(aliases) > 1:
        local = [entry for entry in aliases if entry["platform"] in {"any", platform}]
        if len(local) == 1:
            return local[0]
    if len(aliases) == 1:
        return aliases[0]
    if len(aliases) > 1:
        choices = ", ".join(str(entry["id"]) for entry in aliases)
        raise LauncherError(f"ambiguous script name {name!r}; use one of: {choices}")
    if runnable and any(entry["id"] == name for entry in entries):
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
            entry,
        )
        for entry in usable
    ]
    width = max((len(row[0]) for row in rows), default=4)
    print(f"Usable scripts on {platform}:\n")
    for name, script_id, summary, entry in rows:
        location = "" if name == script_id else f"  [{script_id}]"
        missing = (
            f"  [install {entry['path']}]"
            if entry["external"] and shutil.which(str(entry["path"])) is None
            else ""
        )
        print(f"  {name:<{width}}{location}{missing}\n    {summary}")


def support_matrix(entries: list[dict[str, object]]) -> str:
    lines = [
        "| Command | Linux | macOS | Windows | Privilege | Apply gate | Launcher |",
        "| --- | :---: | :---: | :---: | --- | --- | :---: |",
    ]
    for entry in entries:
        platform = str(entry["platform"])
        support = [
            "yes" if platform in {"any", candidate} else "—"
            for candidate in ("linux", "macos", "windows")
        ]
        privilege = PRIVILEGE_LABELS[str(entry["privilege"])]
        apply_gate = str(entry["apply_flag"] or "—")
        launcher = "run" if entry["launchable"] else "docs"
        lines.append(
            f"| `{entry['id']}` | {' | '.join(support)} | "
            f"{privilege} | `{apply_gate}` | {launcher} |"
        )
    return "\n".join(lines)


def launch(entry: dict[str, object], arguments: list[str]) -> None:
    script = Path(str(entry["path"]))
    if entry["external"]:
        executable = shutil.which(str(script))
        if not executable:
            raise LauncherError(
                f"{script} is not installed; see './run.sh man {entry['alias']}'"
            )
        os.execvp(executable, [executable, *arguments])
        return
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
        if "uv run" in first_line and (uv := shutil.which("uv")):
            command = [uv, "run", "--no-project", "--script", str(script)]
        elif "uv run" in first_line or suffix == ".py":
            command = [sys.executable, str(script)]
        else:
            command = [str(script)]
    os.execvp(command[0], [*command, *arguments])


def show_manual(entry: dict[str, object]) -> int:
    help_path = Path(str(entry["manual"]))
    text = help_path.read_text(encoding="utf-8")
    marker = text.find("\n---\n", 4)
    body = text[marker + 5 :].lstrip()
    if glow := shutil.which("glow"):
        return subprocess.run(
            (glow, "-"), input=body, text=True, check=False
        ).returncode
    print(body, end="" if body.endswith("\n") else "\n")
    return 0


def launch_dashboard(entries: list[dict[str, object]]) -> None:
    uv = shutil.which("uv")
    dashboard = next(entry for entry in entries if entry["id"] == "dev/gui.py")
    assert uv
    os.execvp(uv, (uv, "run", "--script", str(dashboard["path"])))


def self_test(root: Path, entries: list[dict[str, object]]) -> None:
    from unittest.mock import patch

    for platform in ("linux", "macos", "windows"):
        assert compatible(entries, platform)
        assert resolve(entries, platform, "security-audit")["platform"] == "any"
        assert resolve(entries, platform, "clean")["platform"] == platform
        assert (
            resolve(entries, platform, "clean", runnable=False)["platform"] == platform
        )
    assert all(entry["id"] != "dev/gui.py" for entry in compatible(entries, host_os()))
    assert resolve(entries, host_os(), "run.sh", runnable=False)["id"] == "run.sh"
    external = next((entry for entry in entries if entry["external"]), None)
    if external:
        assert not Path(str(external["path"])).is_absolute()
        with (
            patch.object(shutil, "which", return_value="/installed/tool"),
            patch.object(os, "execvp") as execute,
        ):
            launch(external, ["--plain"])
        execute.assert_called_once_with(
            "/installed/tool", ["/installed/tool", "--plain"]
        )
        with patch.object(shutil, "which", return_value=None):
            try:
                launch(external, [])
            except LauncherError as error:
                assert "is not installed" in str(error)
            else:
                raise AssertionError("missing external executable was launched")
    matrix = support_matrix(entries)
    assert all(f"| `{entry['id']}` |" in matrix for entry in entries)
    assert "User; elevation for some actions" in matrix
    assert "User; Slurm account to submit" in matrix
    print(f"ok: {len(entries)} documented scripts and three OS catalogs")


def main(arguments: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        entries = catalog(root)
        platform = host_os()
        if not arguments:
            if sys.stdin.isatty() and shutil.which("uv"):
                launch_dashboard(entries)
            show(entries, platform)
            return 0
        if arguments in (["--help"], ["-h"]):
            print("Usage: ./run.sh <list|matrix|man SCRIPT|script_name> [arguments...]")
            return 0
        if arguments == ["--self-test"]:
            self_test(root, entries)
            return 0
        if arguments == ["list"]:
            show(entries, platform)
            return 0
        if arguments == ["matrix"]:
            print(support_matrix(entries))
            return 0
        if arguments[0] == "man":
            if len(arguments) != 2:
                raise LauncherError("usage: ./run.sh man SCRIPT")
            return show_manual(resolve(entries, platform, arguments[1], runnable=False))
        if arguments[0] in {"list", "matrix"}:
            raise LauncherError(f"{arguments[0]} does not accept arguments")
        launch(resolve(entries, platform, arguments[0]), arguments[1:])
        return 0
    except (LauncherError, OSError, UnicodeError) as error:
        print(f"run.sh: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
