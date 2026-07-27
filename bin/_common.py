"""Small shared helpers for the repository's Python command tools."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class ToolError(Exception):
    """An expected command-line error."""


@dataclass(frozen=True)
class Step:
    label: str
    command: tuple[str, ...]


def host_os() -> str:
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unsupported"


def color(text: str, code: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"\033[{code}m{text}\033[0m"


def heading(text: str) -> None:
    print(color(f"\n{text}", "1;36"), flush=True)


def warning(text: str) -> None:
    print(color(f"warning: {text}", "1;33"), file=sys.stderr, flush=True)


def command_text(command: Sequence[str]) -> str:
    return shlex.join(command)


def find_program(*names: str) -> str | None:
    return next((path for name in names if (path := shutil.which(name))), None)


def require_program(*names: str) -> str:
    program = find_program(*names)
    if program is None:
        raise ToolError(f"required command is missing: {' or '.join(names)}")
    return program


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    check: bool = True,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    print(color(f"$ {command_text(command)}", "2"), flush=True)
    result = subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise ToolError(
            f"{Path(command[0]).name} exited {result.returncode}"
            + (f": {detail}" if detail else "")
        )
    return result


def elevated(command: Sequence[str]) -> tuple[str, ...]:
    if os.name == "nt" or getattr(os, "geteuid", lambda: 1)() == 0:
        return tuple(command)
    return (require_program("sudo", "doas"), *command)


def show_steps(steps: Sequence[Step]) -> None:
    if not steps:
        print("Nothing to do.")
        return
    for number, step in enumerate(steps, 1):
        print(f"{number:>2}. {step.label}")
        print(f"    {command_text(step.command)}")


def confirmed(*, apply: bool, yes: bool, prompt: str) -> bool:
    if not apply:
        print("\nPreview only. Add --apply to perform this plan.")
        return False
    if yes:
        return True
    if not sys.stdin.isatty():
        raise ToolError("--apply needs an interactive terminal or --yes")
    if input(f"\nType APPLY to {prompt}: ").strip() != "APPLY":
        print("Cancelled.")
        return False
    return True


def apply_steps(
    steps: Sequence[Step],
    *,
    apply: bool,
    yes: bool,
    prompt: str,
    cwd: Path | None = None,
) -> bool:
    show_steps(steps)
    if not confirmed(apply=apply, yes=yes, prompt=prompt):
        return False
    for step in steps:
        heading(step.label)
        run(step.command, cwd=cwd)
    return True


def safe_targets(root: Path, patterns: Sequence[str]) -> list[Path]:
    """Resolve declared targets below root without following directory symlinks."""
    root = root.expanduser().resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise ToolError(f"unsafe state root: {root}")
    targets: set[Path] = set()
    for pattern in patterns:
        for target in root.glob(pattern):
            try:
                target.relative_to(root)
            except ValueError as error:
                raise ToolError(f"target escaped state root: {target}") from error
            for parent in target.parents:
                if parent == root:
                    break
                if parent.is_symlink():
                    raise ToolError(f"target crosses a directory symlink: {target}")
            targets.add(target)
    return sorted(targets, key=lambda path: (len(path.parts), str(path)), reverse=True)


def remove_targets(targets: Sequence[Path]) -> tuple[int, int]:
    files = directories = 0
    for target in targets:
        if target.is_symlink() or target.is_file():
            target.unlink(missing_ok=True)
            files += 1
        elif target.is_dir():
            shutil.rmtree(target)
            directories += 1
    return files, directories


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))
