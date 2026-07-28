#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["textual==8.2.8"]
#
# [tool.uv]
# exclude-newer = "2026-07-27T00:00:00Z"
# ///
"""Browse, configure, and run the scripts in this repository."""

from __future__ import annotations

import argparse
import asyncio
import codecs
import io
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (
    Button,
    Checkbox,
    ContentSwitcher,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    ProgressBar,
    RichLog,
    Select,
    Sparkline,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

ARCHIVE_URL = "https://github.com/keys-i/scripts/archive/refs/heads/main.zip"
ARCHIVE_LIMIT = 64 * 1024 * 1024
FILE_PREVIEW_LIMIT = 256 * 1024
OUTPUT_LINE_LIMIT = 8 * 1024
HISTORY_LIMIT = 200
HELP_SUFFIX = ".help"
SEARCH_DIRS = ("bin", "dev", "sys")
FLAG_PATTERN = re.compile(r"^--?[A-Za-z][A-Za-z0-9-]*$")
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
PLATFORMS = {"any", "linux", "macos", "windows"}
SCRIPT_DECK_THEME = Theme(
    name="script-deck",
    primary="#82aaff",
    secondary="#c099ff",
    warning="#ffc777",
    error="#ff757f",
    success="#c3e88d",
    accent="#86e1fc",
    foreground="#c8d3f5",
    background="#181c26",
    surface="#222436",
    panel="#1e2030",
    dark=True,
)


class GuiError(Exception):
    """An error that can be shown directly to the user."""


Conditions = tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class OptionSpec:
    flag: str
    label: str
    warning: str = ""
    when: Conditions = ()


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    label: str
    choices: tuple[tuple[str, str], ...] = ()
    default: str = ""
    flag: str | None = None
    placeholder: str = ""
    required: bool = False
    warning: str = ""
    when: Conditions = ()


@dataclass(frozen=True)
class ScriptSpec:
    script_id: str
    title: str
    summary: str
    platform: str
    path: Path
    markdown: str
    parameters: tuple[ParameterSpec, ...]
    options: tuple[OptionSpec, ...]
    apply_flag: str | None
    yes_flag: str | None
    apply_when: tuple[str, ...] = ()
    direct_when: tuple[str, ...] = ()
    launchable: bool = True

    @property
    def supported(self) -> bool:
        return self.platform in {"any", host_platform()}

    def needs_apply(self, arguments: Iterable[str]) -> bool:
        selected = set(arguments)
        return self.apply_flag is not None and (
            not self.apply_when or bool(selected.intersection(self.apply_when))
        )

    def needs_direct_terminal(self, arguments: Iterable[str]) -> bool:
        return bool(set(arguments).intersection(self.direct_when))


@dataclass(frozen=True)
class RunSelection:
    script: ScriptSpec
    flags: tuple[str, ...]
    working_directory: Path


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    duration: float
    cancelled: bool = False


def host_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unsupported"


def _text(mapping: dict[str, object], key: str, source: Path) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GuiError(f"{source}: {key} must be a non-empty string")
    return value.strip()


def _conditions(
    raw: object,
    controllers: dict[str, set[str]],
    source: Path,
) -> Conditions:
    if raw is None:
        return ()
    if not isinstance(raw, dict) or not raw:
        raise GuiError(f"{source}: when must be a non-empty object")
    conditions: list[tuple[str, tuple[str, ...]]] = []
    for name, values in raw.items():
        if not isinstance(name, str) or name not in controllers:
            raise GuiError(f"{source}: when references unknown choice {name!r}")
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) for value in values)
        ):
            raise GuiError(f"{source}: when.{name} must be a non-empty string array")
        invalid = set(values) - controllers[name]
        if invalid:
            raise GuiError(
                f"{source}: when.{name} has unknown choices "
                f"{', '.join(sorted(invalid))}"
            )
        conditions.append((name, tuple(dict.fromkeys(values))))
    return tuple(conditions)


def _tokens(metadata: dict[str, object], key: str, source: Path) -> tuple[str, ...]:
    raw = metadata.get(key, [])
    if not isinstance(raw, list) or any(
        not isinstance(token, str)
        or not token
        or "\0" in token
        or any(character.isspace() for character in token)
        for token in raw
    ):
        raise GuiError(f"{source}: {key} must be an array of command tokens")
    return tuple(dict.fromkeys(raw))


def conditions_match(
    conditions: Conditions,
    selected: dict[str, str],
) -> bool:
    return all(selected.get(name) in values for name, values in conditions)


def parse_help(help_path: Path, root: Path) -> ScriptSpec:
    try:
        text = help_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError as error:
        raise GuiError(f"cannot read {help_path}: {error}") from error

    if not text.startswith("---\n"):
        raise GuiError(f"{help_path}: expected JSON front matter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise GuiError(f"{help_path}: front matter is not closed")

    try:
        metadata = json.loads(text[4:marker])
    except json.JSONDecodeError as error:
        raise GuiError(f"{help_path}: invalid JSON: {error}") from error
    if not isinstance(metadata, dict):
        raise GuiError(f"{help_path}: front matter must be a JSON object")

    markdown = text[marker + 5 :].strip()
    heading = re.search(r"^# +(.+?)\s*$", markdown, re.MULTILINE)
    if heading is None:
        raise GuiError(f"{help_path}: Markdown needs a level-one heading")

    platform = _text(metadata, "platform", help_path).lower()
    if platform not in PLATFORMS:
        raise GuiError(
            f"{help_path}: platform must be one of {', '.join(sorted(PLATFORMS))}"
        )

    raw_options = metadata.get("options", [])
    if not isinstance(raw_options, list):
        raise GuiError(f"{help_path}: options must be a JSON array")
    options: list[OptionSpec] = []
    option_conditions: list[object] = []
    seen_flags: set[str] = set()
    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            raise GuiError(f"{help_path}: every option must be an object")
        flag = _text(raw_option, "flag", help_path)
        if not FLAG_PATTERN.fullmatch(flag):
            raise GuiError(f"{help_path}: invalid option flag {flag!r}")
        if flag.lower() in seen_flags:
            raise GuiError(f"{help_path}: duplicate option flag {flag}")
        seen_flags.add(flag.lower())
        warning = raw_option.get("warning", "")
        if not isinstance(warning, str):
            raise GuiError(f"{help_path}: option warnings must be strings")
        options.append(
            OptionSpec(
                flag=flag,
                label=_text(raw_option, "label", help_path),
                warning=warning.strip(),
            )
        )
        option_conditions.append(raw_option.get("when"))

    raw_parameters = metadata.get("parameters", [])
    if not isinstance(raw_parameters, list):
        raise GuiError(f"{help_path}: parameters must be a JSON array")
    parameters: list[ParameterSpec] = []
    parameter_conditions: list[object] = []
    seen_names: set[str] = set()
    parameter_flags: set[str] = set()
    for raw_parameter in raw_parameters:
        if not isinstance(raw_parameter, dict):
            raise GuiError(f"{help_path}: every parameter must be an object")
        name = _text(raw_parameter, "name", help_path)
        if not NAME_PATTERN.fullmatch(name):
            raise GuiError(f"{help_path}: invalid parameter name {name!r}")
        if name in seen_names:
            raise GuiError(f"{help_path}: duplicate parameter name {name}")
        seen_names.add(name)

        flag = raw_parameter.get("flag")
        if flag is not None and (
            not isinstance(flag, str) or not FLAG_PATTERN.fullmatch(flag)
        ):
            raise GuiError(f"{help_path}: {name} has an invalid flag")
        if isinstance(flag, str):
            lowered_flag = flag.lower()
            if lowered_flag in seen_flags or lowered_flag in parameter_flags:
                raise GuiError(f"{help_path}: duplicate parameter flag {flag}")
            parameter_flags.add(lowered_flag)

        raw_choices = raw_parameter.get("choices", [])
        if not isinstance(raw_choices, list):
            raise GuiError(f"{help_path}: {name} choices must be an array")
        choices: list[tuple[str, str]] = []
        seen_values: set[str] = set()
        for raw_choice in raw_choices:
            if not isinstance(raw_choice, dict):
                raise GuiError(f"{help_path}: {name} choices must be objects")
            value = _text(raw_choice, "value", help_path)
            if "\0" in value or value in seen_values:
                raise GuiError(f"{help_path}: invalid duplicate choice {value!r}")
            seen_values.add(value)
            choices.append((value, _text(raw_choice, "label", help_path)))

        default = raw_parameter.get("default", "")
        placeholder = raw_parameter.get("placeholder", "")
        warning = raw_parameter.get("warning", "")
        for key, value in (
            ("default", default),
            ("placeholder", placeholder),
            ("warning", warning),
        ):
            if not isinstance(value, str) or "\0" in value:
                raise GuiError(f"{help_path}: {name} {key} must be text")
        if choices and default and default not in seen_values:
            raise GuiError(f"{help_path}: {name} default is not a choice")
        required = raw_parameter.get("required", False)
        if not isinstance(required, bool):
            raise GuiError(f"{help_path}: {name} required must be true or false")
        if required and choices and not default:
            raise GuiError(f"{help_path}: required choice {name} needs a default")

        parameters.append(
            ParameterSpec(
                name=name,
                label=_text(raw_parameter, "label", help_path),
                choices=tuple(choices),
                default=default,
                flag=flag,
                placeholder=placeholder,
                required=required,
                warning=warning.strip(),
            )
        )
        parameter_conditions.append(raw_parameter.get("when"))

    controllers = {
        parameter.name: {value for value, _label in parameter.choices}
        for parameter in parameters
        if parameter.choices
    }
    parameters = [
        replace(
            parameter,
            when=_conditions(raw_when, controllers, help_path),
        )
        for parameter, raw_when in zip(
            parameters,
            parameter_conditions,
            strict=True,
        )
    ]
    options = [
        replace(
            option,
            when=_conditions(raw_when, controllers, help_path),
        )
        for option, raw_when in zip(options, option_conditions, strict=True)
    ]

    apply_flag = metadata.get("applyFlag")
    yes_flag = metadata.get("yesFlag")
    if (apply_flag is None) != (yes_flag is None):
        raise GuiError(f"{help_path}: applyFlag and yesFlag must be paired")
    for name, flag in (("applyFlag", apply_flag), ("yesFlag", yes_flag)):
        if flag is not None and (
            not isinstance(flag, str) or not FLAG_PATTERN.fullmatch(flag)
        ):
            raise GuiError(f"{help_path}: {name} is not a valid flag")
    control_flags = {
        flag.lower() for flag in (apply_flag, yes_flag) if isinstance(flag, str)
    }
    if len(control_flags) == 1 and apply_flag is not None:
        raise GuiError(f"{help_path}: applyFlag and yesFlag must differ")
    overlap = seen_flags & control_flags
    overlap |= parameter_flags & control_flags
    if overlap:
        raise GuiError(
            f"{help_path}: apply controls cannot appear in options: "
            f"{', '.join(sorted(overlap))}"
        )
    apply_when = _tokens(metadata, "applyWhen", help_path)
    direct_when = _tokens(metadata, "directWhen", help_path)
    available_tokens = (
        {value for values in controllers.values() for value in values}
        | {option.flag for option in options}
        | {parameter.flag for parameter in parameters if parameter.flag is not None}
    )
    for name, tokens in (("applyWhen", apply_when), ("directWhen", direct_when)):
        invalid = set(tokens) - available_tokens
        if invalid:
            raise GuiError(
                f"{help_path}: {name} has unknown tokens {', '.join(sorted(invalid))}"
            )
    if apply_when and apply_flag is None:
        raise GuiError(f"{help_path}: applyWhen requires applyFlag")
    if direct_when and apply_flag is None:
        raise GuiError(f"{help_path}: directWhen requires applyFlag")

    launchable = metadata.get("launchable", True)
    if not isinstance(launchable, bool):
        raise GuiError(f"{help_path}: launchable must be true or false")

    script_path = Path(str(help_path)[: -len(HELP_SUFFIX)]).resolve()
    if not script_path.is_file():
        raise GuiError(f"{help_path}: adjacent script does not exist")
    try:
        script_id = script_path.relative_to(root).as_posix()
    except ValueError as error:
        raise GuiError(f"{help_path}: script escapes the repository") from error

    documented = markdown.lower()
    for parameter in parameters:
        token = parameter.flag or parameter.name
        if token.lower() not in documented:
            raise GuiError(f"{help_path}: {token} is missing from Markdown")
    for flag in options:
        if flag.flag.lower() not in documented:
            raise GuiError(f"{help_path}: {flag.flag} is missing from Markdown")
    for flag in (apply_flag, yes_flag):
        if flag is not None and flag.lower() not in documented:
            raise GuiError(f"{help_path}: {flag} is missing from Markdown")

    return ScriptSpec(
        script_id=script_id,
        title=heading.group(1).strip(),
        summary=_text(metadata, "summary", help_path),
        platform=platform,
        path=script_path,
        markdown=markdown,
        parameters=tuple(parameters),
        options=tuple(options),
        apply_flag=apply_flag,
        yes_flag=yes_flag,
        apply_when=apply_when,
        direct_when=direct_when,
        launchable=launchable,
    )


def load_catalog(root: Path) -> tuple[ScriptSpec, ...]:
    help_paths = (
        path
        for directory in SEARCH_DIRS
        if (root / directory).is_dir()
        for path in (root / directory).rglob(f"*{HELP_SUFFIX}")
    )
    scripts = tuple(
        sorted(
            (parse_help(path.resolve(), root) for path in help_paths),
            key=lambda script: script.script_id,
        )
    )
    if not scripts:
        raise GuiError(f"{root}: no adjacent *{HELP_SUFFIX} pages found")
    return scripts


def _valid_root(path: Path) -> bool:
    return (
        (path / "README.md").is_file()
        and (path / "sys").is_dir()
        and any((path / directory).is_dir() for directory in SEARCH_DIRS)
    )


def _find_local_root(requested: str | None) -> Path | None:
    if requested is not None:
        root = Path(requested).expanduser().resolve()
        if not _valid_root(root):
            raise GuiError(f"{root}: not a scripts repository")
        return root

    candidates: list[Path] = []
    for start in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        candidates.extend((start, *start.parents))
    for candidate in candidates:
        if _valid_root(candidate):
            return candidate
    return None


def _download_repository(destination: Path) -> Path:
    request = urllib.request.Request(
        ARCHIVE_URL,
        headers={"User-Agent": "keys-i-scripts-gui"},
    )
    try:
        # ARCHIVE_URL is constant; redirects are constrained before any body is read.
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            final_url = urllib.parse.urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in {
                "github.com",
                "codeload.github.com",
            }:
                raise GuiError("repository archive redirected to an unsafe URL")
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > ARCHIVE_LIMIT:
                raise GuiError("repository archive is unexpectedly large")
            archive = response.read(ARCHIVE_LIMIT + 1)
    except (OSError, ValueError) as error:
        raise GuiError(f"cannot fetch the scripts repository: {error}") from error
    if len(archive) > ARCHIVE_LIMIT:
        raise GuiError("repository archive exceeds the safety limit")

    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = bundle.infolist()
            if (
                not members
                or sum(member.file_size for member in members) > ARCHIVE_LIMIT
            ):
                raise GuiError("repository archive expands beyond the safety limit")
            roots: set[str] = set()
            for member in members:
                if "\\" in member.filename:
                    raise GuiError("repository archive contains an unsafe path")
                path = PurePosixPath(member.filename)
                if path.is_absolute() or ".." in path.parts or not path.parts:
                    raise GuiError("repository archive contains an unsafe path")
                roots.add(path.parts[0])
            if len(roots) != 1:
                raise GuiError("repository archive has an unexpected layout")
            bundle.extractall(destination)
    except zipfile.BadZipFile as error:
        raise GuiError("downloaded repository archive is invalid") from error

    root = (destination / roots.pop()).resolve()
    if not _valid_root(root):
        raise GuiError("downloaded archive is not a scripts repository")
    return root


@contextmanager
def repository_root(requested: str | None) -> Iterator[Path]:
    local = _find_local_root(requested)
    if local is not None:
        yield local
        return

    print("Fetching the temporary script catalog…", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="scripts-gui-") as temporary:
        yield _download_repository(Path(temporary))


def _resolve_program(program: str) -> str:
    if os.path.isabs(program):
        if Path(program).is_file():
            return program
        raise GuiError(f"required interpreter is missing: {program}")
    resolved = shutil.which(program)
    if resolved is None:
        raise GuiError(f"required interpreter is not on PATH: {program}")
    return resolved


def command_for(script: ScriptSpec, flags: Iterable[str]) -> list[str]:
    if script.path.suffix.lower() == ".ps1":
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            raise GuiError("PowerShell is required to run this script")
        command = [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script.path),
        ]
        return [*command, *flags]

    try:
        first_line = (
            script.path.open(encoding="utf-8", errors="replace").readline().strip()
        )
    except OSError as error:
        raise GuiError(f"cannot inspect {script.path}: {error}") from error

    if first_line.startswith("#!"):
        command = shlex.split(first_line[2:])
        if command and Path(command[0]).name == "env":
            command.pop(0)
            if command and command[0] == "-S":
                command.pop(0)
        if not command:
            raise GuiError(f"{script.path}: empty shebang")
        command[0] = _resolve_program(command[0])
        return [*command, str(script.path), *flags]

    if script.path.suffix.lower() == ".py":
        return [sys.executable, str(script.path), *flags]
    if os.access(script.path, os.X_OK):
        return [str(script.path), *flags]
    raise GuiError(f"{script.path}: no runnable shebang")


def display_command(command: Iterable[str]) -> str:
    return shlex.join(command)


def terminal_text(line: str) -> Text:
    """Render ANSI/TrueColor output instead of exposing escape sequences."""
    return Text.from_ansi(line)


def read_file_preview(path: Path, root: Path) -> str:
    """Read a bounded regular file without following a final symlink."""
    if path.is_symlink():
        raise GuiError("Symlink previews are disabled")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, ValueError) as error:
        raise GuiError("File is outside the repository") from error

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise GuiError("Only regular files can be previewed")
            data = file.read(FILE_PREVIEW_LIMIT + 1)
    except OSError as error:
        raise GuiError(f"Cannot read {path}: {error}") from error

    truncated = len(data) > FILE_PREVIEW_LIMIT
    text = data[:FILE_PREVIEW_LIMIT].decode("utf-8", errors="replace")
    return text + ("\n\n[preview truncated at 256 KiB]" if truncated else "")


class FilteredDirectoryTree(DirectoryTree):
    """A lazy file tree with a filename filter."""

    def __init__(
        self,
        path: str | Path,
        *,
        nerd_fonts: bool = False,
        directories_only: bool = False,
        **kwargs: object,
    ) -> None:
        self.filter_text = ""
        self.directories_only = directories_only
        super().__init__(path, **kwargs)
        if nerd_fonts:
            self.ICON_FILE = "󰈔 "
            self.ICON_NODE = "󰉋 "
            self.ICON_NODE_EXPANDED = "󰝰 "

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        query = self.filter_text.casefold()
        for path in paths:
            try:
                if path.is_symlink():
                    continue
                is_directory = path.is_dir()
            except OSError:
                continue
            if self.directories_only and not is_directory:
                continue
            if (
                not query
                or query in path.name.casefold()
                or (is_directory and not self.directories_only)
            ):
                yield path


class DirectoryPicker(ModalScreen[Path | None]):
    """Select a working directory with the keyboard or mouse."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    DirectoryPicker {
        align: center middle;
        background: $background 80%;
    }

    DirectoryPicker > #directory-dialog {
        width: 92vw;
        max-width: 94;
        height: 90vh;
        max-height: 36;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }

    DirectoryPicker #directory-tree {
        height: 1fr;
        border: tall $panel-lighten-2;
        margin: 1 0;
    }

    DirectoryPicker #directory-actions {
        height: 3;
        align-horizontal: right;
    }

    DirectoryPicker #directory-actions Button {
        width: 1fr;
        min-width: 1;
    }
    """

    def __init__(self, current: Path, nerd_fonts: bool) -> None:
        super().__init__()
        self.current = current
        self.nerd_fonts = nerd_fonts

    def compose(self) -> ComposeResult:
        root = self.current if self.current.is_dir() else Path.home()
        with Vertical(id="directory-dialog"):
            yield Label("[b]Choose a working directory[/b]")
            yield Input(
                str(root),
                placeholder="Absolute directory path",
                id="directory-path",
            )
            yield Input(
                placeholder="Filter folders in the current level",
                id="directory-filter",
            )
            yield FilteredDirectoryTree(
                root,
                nerd_fonts=self.nerd_fonts,
                directories_only=True,
                id="directory-tree",
            )
            with Horizontal(id="directory-actions"):
                yield Button("Cancel", id="directory-cancel")
                yield Button("Choose", variant="primary", id="directory-choose")

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Changed, "#directory-filter")
    async def filter_tree(self, event: Input.Changed) -> None:
        tree = self.query_one("#directory-tree", FilteredDirectoryTree)
        tree.filter_text = event.value
        await tree.reload()

    @on(DirectoryTree.DirectorySelected, "#directory-tree")
    def select_directory(self, event: DirectoryTree.DirectorySelected) -> None:
        self.query_one("#directory-path", Input).value = str(event.path)

    @on(Input.Submitted, "#directory-path")
    def submit_path(self) -> None:
        self.choose()

    @on(Button.Pressed)
    def press_button(self, event: Button.Pressed) -> None:
        if event.button.id == "directory-cancel":
            self.dismiss(None)
        elif event.button.id == "directory-choose":
            self.choose()

    def choose(self) -> None:
        value = self.query_one("#directory-path", Input).value.strip()
        if not value:
            self.notify("Enter a directory path", severity="error")
            return
        path = Path(value).expanduser()
        try:
            path = path.resolve(strict=True)
        except OSError:
            self.notify("That directory does not exist", severity="error")
            return
        if not path.is_dir():
            self.notify("Choose a directory, not a file", severity="error")
            return
        self.dismiss(path)


class RunWizard(ModalScreen[RunSelection | None]):
    """Configure a script with a small, validated three-step flow."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    RunWizard {
        align: center middle;
        background: $background 80%;
    }

    RunWizard > #wizard-dialog {
        width: 94vw;
        max-width: 96;
        height: 92vh;
        max-height: 38;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }

    RunWizard #wizard-title {
        height: 2;
        text-style: bold;
        color: $accent;
    }

    RunWizard #wizard-pages {
        height: 1fr;
    }

    RunWizard .wizard-page {
        height: 1fr;
        padding: 1;
    }

    RunWizard .field-row {
        height: auto;
    }

    RunWizard .option-warning {
        color: $warning;
        margin: 0 0 1 4;
    }

    RunWizard #wizard-actions {
        height: 3;
        align-horizontal: right;
    }

    RunWizard #wizard-actions Button {
        width: 1fr;
        min-width: 1;
    }

    RunWizard #cwd-row {
        height: 3;
    }

    RunWizard #cwd {
        width: 1fr;
    }
    """

    def __init__(self, script: ScriptSpec, root: Path, nerd_fonts: bool) -> None:
        super().__init__()
        self.script = script
        self.root = root
        self.nerd_fonts = nerd_fonts
        self.step = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard-dialog"):
            yield Label(id="wizard-title")
            with ContentSwitcher(initial="wizard-options", id="wizard-pages"):
                with VerticalScroll(id="wizard-options", classes="wizard-page"):
                    if not self.script.parameters and not self.script.options:
                        yield Static("This script has no optional flags.")
                    for index, parameter in enumerate(self.script.parameters):
                        with Vertical(
                            id=f"parameter-row-{index}",
                            classes="field-row",
                        ):
                            yield Label(parameter.label)
                            if parameter.choices:
                                yield Select(
                                    (
                                        (label, value)
                                        for value, label in parameter.choices
                                    ),
                                    allow_blank=not parameter.required,
                                    value=parameter.default or Select.BLANK,
                                    id=f"parameter-{index}",
                                )
                            else:
                                yield Input(
                                    value=parameter.default,
                                    placeholder=parameter.placeholder,
                                    id=f"parameter-{index}",
                                )
                            if parameter.warning:
                                yield Static(
                                    f"⚠ {parameter.warning}",
                                    classes="option-warning",
                                )
                    for index, option in enumerate(self.script.options):
                        with Vertical(
                            id=f"option-row-{index}",
                            classes="field-row",
                        ):
                            yield Checkbox(
                                f"{option.label}  [dim]{option.flag}[/]",
                                id=f"option-{index}",
                            )
                            if option.warning:
                                yield Static(
                                    f"⚠ {option.warning}",
                                    classes="option-warning",
                                )
                with Vertical(id="wizard-folder", classes="wizard-page"):
                    yield Static("Choose the directory the script should run from.")
                    with Horizontal(id="cwd-row"):
                        yield Input(str(self.root), id="cwd")
                        yield Button("Browse…", id="browse")
                with VerticalScroll(id="wizard-review", classes="wizard-page"):
                    yield Markdown(id="review")
            with Horizontal(id="wizard-actions"):
                yield Button("Cancel", id="wizard-cancel")
                yield Button("Back", id="wizard-back", disabled=True)
                yield Button("Next", variant="primary", id="wizard-next")

    def on_mount(self) -> None:
        self.refresh_conditions()
        self.update_step()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed)
    def press_button(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "wizard-cancel":
                self.dismiss(None)
            case "wizard-back":
                self.step -= 1
                self.update_step()
            case "wizard-next":
                self.advance()
            case "browse":
                current = Path(self.query_one("#cwd", Input).value).expanduser()
                self.app.push_screen(
                    DirectoryPicker(current, self.nerd_fonts),
                    self.set_directory,
                )

    def set_directory(self, path: Path | None) -> None:
        if path is not None:
            self.query_one("#cwd", Input).value = str(path)

    def controller_values(self) -> dict[str, str]:
        selected: dict[str, str] = {}
        for index, parameter in enumerate(self.script.parameters):
            if not parameter.choices:
                continue
            value = self.query_one(f"#parameter-{index}", Select).value
            selected[parameter.name] = "" if value is Select.BLANK else str(value)
        return selected

    def refresh_conditions(self) -> None:
        selected = self.controller_values()
        for index, parameter in enumerate(self.script.parameters):
            self.query_one(f"#parameter-row-{index}").display = conditions_match(
                parameter.when,
                selected,
            )
        for index, option in enumerate(self.script.options):
            self.query_one(f"#option-row-{index}").display = conditions_match(
                option.when,
                selected,
            )

    @on(Select.Changed)
    def select_changed(self, _event: Select.Changed) -> None:
        self.refresh_conditions()

    def selected_arguments(self) -> tuple[str, ...] | None:
        arguments: list[str] = []
        selected = self.controller_values()
        for index, parameter in enumerate(self.script.parameters):
            if not conditions_match(parameter.when, selected):
                continue
            widget = self.query_one(f"#parameter-{index}", Input | Select)
            value = (
                widget.value.strip()
                if isinstance(widget, Input)
                else ""
                if widget.value is Select.BLANK
                else str(widget.value)
            )
            if parameter.required and not value:
                self.notify(f"{parameter.label} is required", severity="error")
                return None
            if value:
                if parameter.flag is not None:
                    arguments.append(parameter.flag)
                arguments.append(value)
        arguments.extend(
            option.flag
            for index, option in enumerate(self.script.options)
            if conditions_match(option.when, selected)
            and self.query_one(f"#option-{index}", Checkbox).value
        )
        return tuple(arguments)

    def working_directory(self) -> Path | None:
        value = self.query_one("#cwd", Input).value.strip()
        if not value:
            self.notify("Enter a working directory", severity="error")
            return None
        try:
            path = Path(value).expanduser().resolve(strict=True)
        except OSError:
            self.notify("Working directory does not exist", severity="error")
            return None
        if not path.is_dir():
            self.notify("Working directory is not a directory", severity="error")
            return None
        return path

    def update_step(self) -> None:
        names = ("Options", "Working directory", "Review")
        self.query_one("#wizard-title", Label).update(
            f"{self.script.title}  ·  {self.step + 1}/3 {names[self.step]}"
        )
        self.query_one("#wizard-pages", ContentSwitcher).current = (
            "wizard-options",
            "wizard-folder",
            "wizard-review",
        )[self.step]
        self.query_one("#wizard-back", Button).disabled = self.step == 0
        arguments = self.selected_arguments() if self.step == 2 else ()
        self.query_one("#wizard-next", Button).label = (
            ("Preview" if self.script.needs_apply(arguments or ()) else "Run")
            if self.step == 2
            else "Next"
        )

    def advance(self) -> None:
        if self.step < 1:
            self.step += 1
            self.update_step()
            self.query_one("#cwd", Input).focus()
            return

        directory = self.working_directory()
        if directory is None:
            return
        if self.step == 1:
            arguments = self.selected_arguments()
            if arguments is None:
                return
            try:
                preview = display_command(command_for(self.script, arguments))
            except GuiError as error:
                self.notify(str(error), severity="error")
                return
            warnings = [
                option.warning
                for option in self.script.options
                if conditions_match(option.when, self.controller_values())
                and option.flag in arguments
                and option.warning
            ]
            warnings.extend(
                parameter.warning
                for parameter in self.script.parameters
                if conditions_match(parameter.when, self.controller_values())
                and parameter.warning
            )
            caution = "\n".join(f"- {warning}" for warning in warnings)
            needs_apply = self.script.needs_apply(arguments)
            flow = (
                "This runs a read-only preview first, then shows the apply "
                "command for a direct interactive terminal."
                if needs_apply and self.script.needs_direct_terminal(arguments)
                else "This runs a read-only preview first. Apply repeats "
                "discovery with the same settings, so targets may change "
                "between runs. A successful preview must be followed by `CLEAN`."
                if needs_apply
                else "This script starts as soon as you confirm this step."
            )
            self.query_one("#review", Markdown).update(
                f"# Review\n\n{flow}\n\n"
                f"**Working directory:** `{directory}`\n\n"
                f"```text\n{preview}\n```\n\n"
                + (f"## Warnings\n\n{caution}\n" if caution else "")
            )
            self.step += 1
            self.update_step()
            return

        arguments = self.selected_arguments()
        if arguments is not None:
            self.dismiss(RunSelection(self.script, arguments, directory))


class ConfirmApply(ModalScreen[bool]):
    """Require an explicit destructive-action confirmation."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    ConfirmApply {
        align: center middle;
        background: $background 85%;
    }

    ConfirmApply > #confirm-dialog {
        width: 92vw;
        max-width: 82;
        height: auto;
        max-height: 90vh;
        border: heavy $warning;
        background: $surface;
        padding: 1 2;
    }

    ConfirmApply #confirm-command {
        height: auto;
        max-height: 8;
        overflow-y: auto;
        background: $panel;
        padding: 1;
        margin: 1 0;
    }

    ConfirmApply #confirm-actions {
        height: 3;
        align-horizontal: right;
    }

    ConfirmApply #confirm-actions Button {
        width: 1fr;
        min-width: 1;
    }
    """

    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label("[b yellow]Preview passed[/b yellow]")
            yield Static(
                "Apply repeats discovery with the same settings. Targets may "
                "have changed since the preview."
            )
            yield Static(self.command, id="confirm-command")
            yield Label("Type [b]CLEAN[/b] to enable Apply:")
            yield Input(placeholder="CLEAN", id="confirmation")
            with Horizontal(id="confirm-actions"):
                yield Button("Cancel", id="confirm-cancel")
                yield Button(
                    "Apply",
                    variant="warning",
                    id="confirm-apply",
                    disabled=True,
                )

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Input.Changed, "#confirmation")
    def validate_confirmation(self, event: Input.Changed) -> None:
        self.query_one("#confirm-apply", Button).disabled = event.value != "CLEAN"

    @on(Input.Submitted, "#confirmation")
    def submit_confirmation(self, event: Input.Submitted) -> None:
        if event.value == "CLEAN":
            self.dismiss(True)

    @on(Button.Pressed)
    def press_button(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-apply":
            self.dismiss(True)
        elif event.button.id == "confirm-cancel":
            self.dismiss(False)


class ScriptsApp(App[None]):
    """Responsive dashboard for the repository's documented scripts."""

    TITLE = "Scripts"
    SUB_TITLE = "A small toolbox, one calm interface"
    ENABLE_COMMAND_PALETTE = True
    INLINE_PADDING = 0
    HORIZONTAL_BREAKPOINTS: ClassVar[list[tuple[int, str]]] = [
        (0, "-compact"),
        (88, "-normal"),
        (126, "-wide"),
    ]
    VERTICAL_BREAKPOINTS: ClassVar[list[tuple[int, str]]] = [
        (0, "-short"),
        (28, "-tall"),
    ]
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("ctrl+q", "quit", "Quit"),
        ("/", "focus_filter", "Filter"),
        ("f1,question_mark", "help_tab", "Help"),
        ("f2", "run", "Run"),
        ("f3", "files", "Files"),
        ("f5", "sort", "Sort"),
        ("escape", "cancel_run", "Cancel"),
    ]

    CSS = """
    Screen {
        background: $background;
        color: $text;
    }

    Screen:inline {
        height: 75vh;
        min-height: 16;
        max-height: 42;
        border: none;
    }

    Header {
        background: $primary-background;
        color: $text;
    }

    #shell {
        height: 1fr;
        padding: 0 1;
    }

    #hero {
        height: 5;
        padding: 1 2;
        background: $surface;
        border-bottom: tall $primary;
    }

    #brand {
        width: 1fr;
        color: $accent;
        text-style: bold;
    }

    #status {
        width: auto;
        content-align: right middle;
        color: $text-muted;
    }

    #toolbar {
        height: 4;
        padding: 1 0 0 0;
    }

    #script-filter {
        width: 1fr;
    }

    #theme {
        width: 22;
        margin-left: 1;
    }

    #toolbar Button {
        min-width: 10;
        margin-left: 1;
    }

    #workspace {
        height: 1fr;
        layout: horizontal;
    }

    #catalog-panel {
        width: 42%;
        min-width: 32;
        height: 1fr;
        border: round $primary;
        background: $surface;
    }

    #catalog-heading {
        height: 2;
        padding: 0 1;
        color: $accent;
        text-style: bold;
    }

    #scripts {
        height: 1fr;
    }

    #details-tabs {
        width: 1fr;
        height: 1fr;
        margin-left: 1;
    }

    TabPane {
        padding: 0 1;
    }

    #help {
        height: 1fr;
    }

    #activity-heading {
        height: 2;
        color: $accent;
        text-style: bold;
    }

    #progress {
        height: 2;
        display: none;
    }

    #run-log {
        height: 1fr;
        border: tall $panel-lighten-2;
        background: $surface;
        padding: 0 1;
    }

    #activity-actions {
        height: 3;
        align-horizontal: right;
    }

    #history {
        height: 1fr;
    }

    #durations {
        height: 3;
        color: $accent;
    }

    #file-filter {
        height: 3;
    }

    #file-browser {
        height: 1fr;
    }

    #repo-tree {
        width: 42%;
        min-width: 24;
        border: tall $panel-lighten-2;
    }

    #repo-tree > .directory-tree--folder {
        color: $accent;
    }

    #repo-tree > .directory-tree--extension {
        color: $text-muted;
    }

    #file-preview {
        width: 1fr;
        margin-left: 1;
        border: tall $panel-lighten-2;
    }

    Footer {
        background: $primary-background;
    }

    Screen.-compact #hero {
        height: 3;
        padding: 0 1;
    }

    Screen.-compact #status {
        display: none;
    }

    Screen.-compact #toolbar {
        height: 7;
        layout: grid;
        grid-size: 4 2;
        grid-columns: 1fr 1fr 1fr 1fr;
        grid-rows: 3 3;
        grid-gutter: 0 1;
    }

    Screen.-compact #script-filter {
        column-span: 3;
        width: 100%;
    }

    Screen.-compact #theme {
        width: 100%;
        margin-left: 0;
    }

    Screen.-compact #toolbar Button {
        width: 100%;
        min-width: 1;
        margin-left: 0;
    }

    Screen.-compact #run, Screen.-compact #files-button {
        column-span: 2;
    }

    Screen.-compact #workspace {
        layout: vertical;
    }

    Screen.-compact #catalog-panel {
        width: 100%;
        min-width: 1;
        height: 10;
    }

    Screen.-compact #details-tabs {
        width: 100%;
        height: 1fr;
        margin-left: 0;
        margin-top: 1;
    }

    Screen.-compact #file-browser {
        layout: vertical;
    }

    Screen.-compact #repo-tree {
        width: 100%;
        min-width: 1;
        height: 45%;
    }

    Screen.-compact #file-preview {
        width: 100%;
        height: 1fr;
        margin-left: 0;
        margin-top: 1;
    }

    Screen.-short #hero {
        display: none;
    }

    Screen.-short #toolbar {
        padding-top: 0;
    }

    Screen.-short.-compact #catalog-panel {
        height: 4;
    }

    Screen.-short.-compact #catalog-heading {
        display: none;
    }
    """

    def __init__(
        self,
        root: Path,
        scripts: tuple[ScriptSpec, ...],
        *,
        nerd_fonts: bool = False,
    ) -> None:
        super().__init__()
        self.register_theme(SCRIPT_DECK_THEME)
        self.root = root
        self.scripts = scripts
        self.nerd_fonts = nerd_fonts
        self.selected: ScriptSpec | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.started_at: float | None = None
        self.active_script: ScriptSpec | None = None
        self.active_phase = ""
        self.cancel_requested = False
        self.durations: list[float] = []
        self.history_index = 0
        self.sort_column: str | None = None
        self.sort_reverse = False
        self.catalog_query: str | None = None
        self.search_text = {
            script.script_id: (
                f"{script.script_id} {script.title} {script.summary} {script.platform}"
            ).casefold()
            for script in scripts
        }

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="shell"):
            with Horizontal(id="hero"):
                yield Static(
                    "◈ SCRIPT DECK\n[dim]discover · preview · run[/dim]",
                    id="brand",
                )
                yield Static(id="status")
            with Horizontal(id="toolbar"):
                yield Input(
                    placeholder="Filter scripts  /",
                    id="script-filter",
                )
                yield Select(
                    [
                        ("Script Deck", "script-deck"),
                        ("Tokyo Night", "tokyo-night"),
                        ("Nord", "nord"),
                        ("Dracula", "dracula"),
                        ("Gruvbox", "gruvbox"),
                        ("Light", "textual-light"),
                    ],
                    value="script-deck",
                    allow_blank=False,
                    id="theme",
                )
                yield Button("Run", variant="primary", id="run")
                yield Button("Files", id="files-button")
            with Horizontal(id="workspace"):
                with Vertical(id="catalog-panel"):
                    yield Label("SCRIPTS", id="catalog-heading")
                    yield DataTable(
                        cursor_type="row",
                        zebra_stripes=True,
                        id="scripts",
                    )
                with TabbedContent(id="details-tabs"):
                    with TabPane("Help", id="help-pane"):
                        yield Markdown(id="help")
                    with TabPane("Output", id="output-pane"):
                        yield Label("Ready", id="activity-heading")
                        yield ProgressBar(
                            total=None,
                            show_percentage=False,
                            show_eta=False,
                            id="progress",
                        )
                        yield RichLog(
                            highlight=True,
                            markup=False,
                            wrap=True,
                            max_lines=2_000,
                            id="run-log",
                        )
                        with Horizontal(id="activity-actions"):
                            yield Button(
                                "Cancel",
                                variant="error",
                                id="cancel",
                                disabled=True,
                            )
                    with TabPane("History", id="history-pane"):
                        yield Sparkline(
                            [0],
                            min_color="#c3e88d",
                            max_color="#ffc777",
                            id="durations",
                        )
                        yield DataTable(
                            cursor_type="row",
                            zebra_stripes=True,
                            id="history",
                        )
                    with TabPane("Files", id="files-pane"):
                        yield Input(
                            placeholder="Filter expanded folders",
                            id="file-filter",
                        )
                        with Horizontal(id="file-browser"):
                            yield FilteredDirectoryTree(
                                self.root,
                                nerd_fonts=self.nerd_fonts,
                                id="repo-tree",
                            )
                            yield TextArea(
                                read_only=True,
                                show_line_numbers=True,
                                placeholder="Select a file to preview it",
                                id="file-preview",
                            )
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "script-deck"
        table = self.query_one("#scripts", DataTable)
        table.add_column("State", key="state")
        table.add_column("Script", key="script")
        table.add_column("OS", key="platform")
        table.add_column("Summary", key="summary")
        history = self.query_one("#history", DataTable)
        history.add_columns("Time", "Script", "Phase", "Result", "Seconds")
        self.refresh_catalog()
        self.set_interval(0.25, self.update_elapsed)

    def refresh_catalog(self, query: str = "") -> None:
        if query == self.catalog_query:
            return
        self.catalog_query = query
        previous_id = self.selected.script_id if self.selected is not None else None
        words = query.casefold().split()
        visible = [
            script
            for script in self.scripts
            if all(word in self.search_text[script.script_id] for word in words)
        ]
        visible.sort(
            key=lambda script: (
                not (script.supported and script.launchable),
                not script.supported,
                script.script_id,
            )
        )
        table = self.query_one("#scripts", DataTable)
        table.clear()
        for script in visible:
            ready = script.supported and script.launchable
            state = Text(
                "●" if ready else "◆" if not script.launchable else "○",
                style=(
                    "green"
                    if ready
                    else "bright_blue"
                    if not script.launchable
                    else "bright_black"
                ),
            )
            table.add_row(
                state,
                script.title,
                script.platform,
                script.summary,
                key=script.script_id,
            )
        if self.sort_column is not None:
            table.sort(
                self.sort_column,
                key=lambda value: str(value).casefold(),
                reverse=self.sort_reverse,
            )
        self.selected = next(
            (script for script in visible if script.script_id == previous_id),
            visible[0] if visible else None,
        )
        if visible:
            assert self.selected is not None
            table.move_cursor(
                row=table.get_row_index(self.selected.script_id),
                column=0,
            )
            self.show_script(self.selected)
        else:
            self.query_one("#help", Markdown).update(
                "# No matches\n\nTry a shorter filter."
            )
        self.update_controls()

    def show_script(self, script: ScriptSpec) -> None:
        self.selected = script
        badge = (
            "Documentation only"
            if not script.launchable
            else "Available on this computer"
            if script.supported
            else f"Available on {script.platform}"
        )
        self.query_one("#help", Markdown).update(
            f"> **{badge}** · `{script.script_id}`\n\n{script.markdown}"
        )
        self.update_controls()

    def update_controls(self) -> None:
        available = (
            self.selected is not None
            and self.selected.supported
            and self.selected.launchable
            and self.started_at is None
        )
        self.query_one("#run", Button).disabled = not available
        self.query_one("#cancel", Button).disabled = self.process is None
        supported = sum(
            script.supported and script.launchable for script in self.scripts
        )
        state = "running" if self.started_at is not None else "ready"
        self.query_one("#status", Static).update(
            f"[b]{supported} of {len(self.scripts)}[/b] available · "
            f"{host_platform()} · {state}"
        )

    @on(Input.Changed, "#script-filter")
    def filter_scripts(self, event: Input.Changed) -> None:
        self.refresh_catalog_later(event.value)

    @work(group="catalog-filter", exclusive=True)
    async def refresh_catalog_later(self, query: str) -> None:
        await asyncio.sleep(0.12)
        self.refresh_catalog(query)

    @on(Input.Changed, "#file-filter")
    def filter_files(self, event: Input.Changed) -> None:
        self.reload_file_tree(event.value)

    @work(group="file-filter", exclusive=True)
    async def reload_file_tree(self, query: str) -> None:
        await asyncio.sleep(0.12)
        tree = self.query_one("#repo-tree", FilteredDirectoryTree)
        tree.filter_text = query
        await tree.reload()

    @on(Select.Changed, "#theme")
    def change_theme(self, event: Select.Changed) -> None:
        if isinstance(event.value, str):
            self.theme = event.value

    @on(DataTable.RowHighlighted, "#scripts")
    def highlight_script(self, event: DataTable.RowHighlighted) -> None:
        script_id = str(event.row_key.value)
        script = next(
            (item for item in self.scripts if item.script_id == script_id),
            None,
        )
        if script is not None:
            self.show_script(script)

    @on(DataTable.HeaderSelected, "#scripts")
    def sort_scripts(self, event: DataTable.HeaderSelected) -> None:
        assert event.column_key.value is not None
        self.apply_sort(str(event.column_key.value))

    def apply_sort(self, column: str) -> None:
        self.sort_reverse = (
            not self.sort_reverse if column == self.sort_column else False
        )
        self.sort_column = column
        table = self.query_one("#scripts", DataTable)
        table.sort(
            column,
            key=lambda value: str(value).casefold(),
            reverse=self.sort_reverse,
        )
        if self.selected is not None:
            table.move_cursor(
                row=table.get_row_index(self.selected.script_id),
                column=table.cursor_coordinate.column,
            )

    @on(DirectoryTree.FileSelected, "#repo-tree")
    async def preview_file(self, event: DirectoryTree.FileSelected) -> None:
        preview = self.query_one("#file-preview", TextArea)
        try:
            text = await asyncio.to_thread(
                read_file_preview,
                event.path,
                self.root,
            )
        except GuiError as error:
            text = str(error)
        preview.load_text(text)

    @on(Button.Pressed)
    def press_button(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "run":
                self.action_run()
            case "files-button":
                self.action_files()
            case "cancel":
                self.action_cancel_run()

    def action_focus_filter(self) -> None:
        self.query_one("#script-filter", Input).focus()

    def action_help_tab(self) -> None:
        self.query_one("#details-tabs", TabbedContent).active = "help-pane"

    def action_files(self) -> None:
        self.query_one("#details-tabs", TabbedContent).active = "files-pane"
        self.query_one("#file-filter", Input).focus()

    def action_sort(self) -> None:
        self.apply_sort("script")

    def action_run(self) -> None:
        if (
            self.selected is None
            or not self.selected.supported
            or not self.selected.launchable
            or self.started_at is not None
        ):
            return
        self.push_screen(
            RunWizard(self.selected, self.root, self.nerd_fonts),
            self.start_selection,
        )

    def start_selection(self, selection: RunSelection | None) -> None:
        if selection is not None:
            self.run_selection(selection)

    def action_cancel_run(self) -> None:
        if self.process is not None:
            self.cancel_requested = True
            self.run_worker(
                self.stop_process(),
                group="cancel",
                exclusive=True,
            )

    def begin_activity(self, script: ScriptSpec, phase: str) -> None:
        self.query_one("#details-tabs", TabbedContent).active = "output-pane"
        self.query_one("#activity-heading", Label).update(
            f"{phase} · {script.title} · 0.0s"
        )
        log = self.query_one("#run-log", RichLog)
        log.clear()
        self.query_one("#progress", ProgressBar).display = True
        self.started_at = time.monotonic()
        self.active_script = script
        self.active_phase = phase
        self.cancel_requested = False
        self.update_controls()

    def update_elapsed(self) -> None:
        if self.started_at is None or self.active_script is None:
            return
        elapsed = time.monotonic() - self.started_at
        self.query_one("#activity-heading", Label).update(
            f"{self.active_phase} · {self.active_script.title} · {elapsed:.1f}s"
        )

    def record(
        self,
        script: ScriptSpec,
        phase: str,
        result: RunResult,
    ) -> None:
        status = "cancelled" if result.cancelled else str(result.exit_code)
        style = (
            "yellow"
            if result.cancelled
            else "green"
            if result.exit_code == 0
            else "red"
        )
        history = self.query_one("#history", DataTable)
        if history.row_count >= HISTORY_LIMIT:
            history.remove_row(f"history-{self.history_index - HISTORY_LIMIT}")
        history.add_row(
            datetime.now().astimezone().strftime("%H:%M:%S"),
            script.title,
            phase,
            Text(status, style=style),
            f"{result.duration:.1f}",
            key=f"history-{self.history_index}",
        )
        self.history_index += 1
        self.durations.append(result.duration)
        del self.durations[:-HISTORY_LIMIT]
        self.query_one("#durations", Sparkline).data = self.durations

    async def run_once(
        self,
        selection: RunSelection,
        phase: str,
        flags: Iterable[str],
    ) -> RunResult:
        command = command_for(selection.script, flags)
        self.begin_activity(selection.script, phase)
        log = self.query_one("#run-log", RichLog)
        log.write(f"$ {display_command(command)}")
        environment = os.environ.copy()
        environment["SCRIPTS_TUI"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        started = time.monotonic()
        kwargs: dict[str, object] = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        elif os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                cwd=selection.working_directory,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **kwargs,
            )
            self.update_controls()
            assert self.process.stdout is not None
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            fragment = ""
            truncated = False
            while chunk := await self.process.stdout.read(8_192):
                fragment += decoder.decode(chunk)
                while "\n" in fragment:
                    line, fragment = fragment.split("\n", 1)
                    if truncated:
                        truncated = False
                    else:
                        line = line.rstrip("\r")
                        rendered = (
                            line
                            if len(line) <= OUTPUT_LINE_LIMIT
                            else line[:OUTPUT_LINE_LIMIT]
                            + " … [line truncated at 8 KiB]"
                        )
                        log.write(terminal_text(rendered))
                if truncated:
                    fragment = ""
                elif len(fragment) > OUTPUT_LINE_LIMIT:
                    # ponytail: cap pathological lines; use a file viewer if
                    # retaining complete machine-generated output becomes useful.
                    log.write(
                        terminal_text(
                            fragment[:OUTPUT_LINE_LIMIT]
                            + " … [line truncated at 8 KiB]"
                        )
                    )
                    fragment = ""
                    truncated = True
            fragment += decoder.decode(b"", final=True)
            if fragment and not truncated:
                log.write(terminal_text(fragment))
            exit_code = await self.process.wait()
            result = RunResult(
                exit_code,
                time.monotonic() - started,
                self.cancel_requested,
            )
        except asyncio.CancelledError:
            await self.stop_process()
            raise
        except OSError as error:
            await self.stop_process()
            log.write(f"error: {error}")
            result = RunResult(127, time.monotonic() - started)
        finally:
            await self.stop_process()
            self.process = None
            self.started_at = None
            self.active_script = None
            self.active_phase = ""
            self.query_one("#progress", ProgressBar).display = False
            self.update_controls()

        label = (
            "cancelled"
            if result.cancelled
            else "passed"
            if result.exit_code == 0
            else "failed"
        )
        self.query_one("#activity-heading", Label).update(
            f"{phase} {label} · exit {result.exit_code} · {result.duration:.1f}s"
        )
        self.record(selection.script, phase, result)
        return result

    @work(group="script", exclusive=True)
    async def run_selection(self, selection: RunSelection) -> None:
        try:
            needs_apply = selection.script.needs_apply(selection.flags)
            result = await self.run_once(
                selection,
                "Preview" if needs_apply else "Run",
                selection.flags,
            )
            if not needs_apply or result.exit_code != 0 or result.cancelled:
                return
            assert selection.script.apply_flag is not None
            assert selection.script.yes_flag is not None
            if selection.script.needs_direct_terminal(selection.flags):
                direct_flags = (*selection.flags, selection.script.apply_flag)
                command = display_command(command_for(selection.script, direct_flags))
                self.query_one("#activity-heading", Label).update(
                    "Preview passed · direct terminal required"
                )
                self.query_one("#run-log", RichLog).write(
                    "Interactive work cannot run inside the dashboard.\n"
                    f"Run directly:\n$ {command}"
                )
                return
            apply_flags = (
                *selection.flags,
                selection.script.apply_flag,
                selection.script.yes_flag,
            )
            command = display_command(command_for(selection.script, apply_flags))
            confirmed = await self.push_screen_wait(ConfirmApply(command))
            if confirmed:
                await self.run_once(selection, "Apply", apply_flags)
            else:
                self.query_one("#run-log", RichLog).write("Apply cancelled.")
        except GuiError as error:
            self.notify(str(error), severity="error")

    async def stop_process(self) -> None:
        process = self.process
        if process is None or process.returncode is not None:
            return
        self.query_one("#run-log", RichLog).write("Cancelling process…")
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        elif shutil.which("taskkill"):
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            process.kill()
            await process.wait()


async def self_test(root: Path, scripts: tuple[ScriptSpec, ...]) -> None:
    expected = {"linux", "macos", "windows"}
    color = terminal_text("\x1b[38;2;1;2;3mcolor\x1b[0m")
    assert color.plain == "color" and color.spans
    if not expected.issubset({script.platform for script in scripts}):
        raise GuiError("self-test needs Linux, macOS, and Windows help pages")
    dashboard = next(
        (script for script in scripts if script.script_id == "dev/gui.py"),
        None,
    )
    if dashboard is None or dashboard.launchable:
        raise GuiError("dashboard help must be present and non-launchable")

    with tempfile.TemporaryDirectory(prefix="scripts-gui-contract-") as directory:
        contract_root = Path(directory).resolve()
        script_path = contract_root / "bin" / "probe.py"
        script_path.parent.mkdir()
        script_path.write_text("print('ok')\n", encoding="utf-8")
        metadata = {
            "summary": "Exercise typed parameters.",
            "platform": "any",
            "applyFlag": "--apply",
            "yesFlag": "--yes",
            "applyWhen": ["fix"],
            "directWhen": ["fix"],
            "launchable": False,
            "parameters": [
                {
                    "name": "action",
                    "label": "Action",
                    "required": True,
                    "default": "show",
                    "choices": [
                        {"value": "show", "label": "Show"},
                        {"value": "fix", "label": "Fix"},
                    ],
                },
                {
                    "name": "query",
                    "label": "Query",
                    "flag": "--query",
                    "placeholder": "optional text",
                    "when": {"action": ["fix"]},
                },
            ],
        }
        help_path = script_path.with_name("probe.py.help")
        help_path.write_text(
            f"---\n{json.dumps(metadata)}\n---\n"
            "# Probe\n\n`action`, `--query`, `--apply`, and `--yes` exercise "
            "typed parameters.\n",
            encoding="utf-8",
        )
        probe = parse_help(help_path, contract_root)
        assert probe.parameters[0].default == "show"
        assert probe.parameters[1].flag == "--query"
        assert not probe.launchable
        assert not probe.needs_apply(("show",))
        assert probe.needs_apply(("fix",))
        assert probe.needs_direct_terminal(("fix",))
        assert not conditions_match(
            probe.parameters[1].when,
            {"action": "show"},
        )

    compact = ScriptsApp(root, scripts)
    async with compact.run_test(size=(50, 18)) as pilot:
        await pilot.pause()
        assert compact.screen.has_class("-compact")
        table = compact.query_one("#scripts", DataTable)
        assert table.row_count == len(scripts)
        details = compact.query_one("#details-tabs", TabbedContent).region
        help_region = compact.query_one("#help", Markdown).region
        assert details.height > 0 and details.y < compact.size.height
        assert help_region.height > 0 and help_region.y < compact.size.height
        compact.show_script(dashboard)
        assert compact.query_one("#run", Button).disabled
        compact.action_run()
        assert not isinstance(compact.screen, RunWizard)
        runnable = next(
            script for script in scripts if script.supported and script.launchable
        )
        compact.show_script(runnable)
        await pilot.press("/")
        assert compact.focused is compact.query_one("#script-filter", Input)
        assert await pilot.click("#files-button")
        assert compact.query_one("#details-tabs", TabbedContent).active == "files-pane"
        selected_id = compact.selected.script_id if compact.selected else ""
        compact.action_sort()
        assert table.cursor_coordinate.row == table.get_row_index(selected_id)

        compact.action_run()
        await pilot.pause()
        assert isinstance(compact.screen, RunWizard)
        assert await pilot.click("#wizard-next")
        wizard = compact.screen
        assert isinstance(wizard, RunWizard) and wizard.step == 1
        wizard.query_one("#cwd", Input).value = ""
        await pilot.pause(0.3)
        assert await pilot.click("#wizard-next")
        assert wizard.step == 1
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(compact.screen, ModalScreen)
        compact.push_screen(RunWizard(probe, root, False))
        await pilot.pause()
        conditional_wizard = compact.screen
        assert isinstance(conditional_wizard, RunWizard)
        hidden_query = conditional_wizard.query_one("#parameter-1", Input)
        hidden_query.value = "ignored"
        assert not conditional_wizard.query_one("#parameter-row-1").display
        assert conditional_wizard.selected_arguments() == ("show",)
        conditional_wizard.query_one("#parameter-0", Select).value = "fix"
        await pilot.pause()
        assert conditional_wizard.query_one("#parameter-row-1").display
        assert conditional_wizard.selected_arguments() == (
            "fix",
            "--query",
            "ignored",
        )
        await pilot.press("escape")
        await pilot.pause()

    wide = ScriptsApp(root, scripts)
    async with wide.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert wide.screen.has_class("-wide")
        with tempfile.TemporaryDirectory(prefix="scripts-gui-test-") as directory:
            test_root = Path(directory)
            probe = test_root / "long-line.py"
            probe.write_text("print('x' * 70000)\n", encoding="utf-8")
            script = ScriptSpec(
                "long-line.py",
                "Long output",
                "Exercise bounded output streaming.",
                "any",
                probe,
                "# Long output",
                (),
                (),
                None,
                None,
            )
            for _index in range(HISTORY_LIMIT + 1):
                wide.record(script, "History test", RunResult(0, 0.1))
            assert wide.query_one("#history", DataTable).row_count == HISTORY_LIMIT
            assert len(wide.durations) == HISTORY_LIMIT
            result = await wide.run_once(
                RunSelection(script, (), test_root),
                "Stream test",
                (),
            )
            assert result.exit_code == 0 and not result.cancelled

    print(f"ok: {len(scripts)} scripts, compact and wide layouts")


def parse_args(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Browse documented scripts, preview destructive work, and run "
            "everything from one responsive terminal interface."
        )
    )
    parser.add_argument(
        "--root",
        metavar="PATH",
        help="use a local scripts checkout instead of automatic discovery",
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="run below the prompt instead of full-screen (macOS/Linux)",
    )
    parser.add_argument(
        "--nerd-fonts",
        action="store_true",
        help="use Nerd Font file and folder icons",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="validate help contracts and render compact and wide layouts",
    )
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if arguments is None else arguments)
    try:
        with repository_root(args.root) as root:
            scripts = load_catalog(root)
            if args.self_test:
                asyncio.run(self_test(root, scripts))
                return 0
            inline = args.inline
            if inline and os.name == "nt":
                print(
                    "Inline mode is unavailable on Windows; using full-screen.",
                    file=sys.stderr,
                )
                inline = False
            ScriptsApp(
                root,
                scripts,
                nerd_fonts=args.nerd_fonts,
            ).run(inline=inline)
            return 0
    except GuiError as error:
        print(f"gui: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
