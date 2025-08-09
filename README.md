# Scripts

A home for the small scripts I keep reaching for.

Some came from HPC work, some fix annoying system problems, and others are
little command-line tools that save me from repeating the same steps. They live
here because they are useful, not because they need to become full projects.

## Using a Script

The easiest way to use the collection is the interactive dashboard. It finds
the right script, renders its help page, guides you through the available
options, and streams the output:

```sh
uv run --refresh "https://raw.githubusercontent.com/keys-i/scripts/main/dev/gui.py"
```

The same command works in PowerShell. It needs
[`uv`](https://docs.astral.sh/uv/getting-started/installation/), but it does not
need a clone or a Python setup: `uv` runs the pinned dependencies in an isolated
environment, and the dashboard removes its temporary repository copy when it
closes.

The dashboard is full-screen by default. On macOS and Linux, add `--inline` to
keep it below the prompt. Add `--nerd-fonts` when your terminal uses a Nerd
Font. Use `/` to filter, `F1` for help, `F2` to run, `F3` for files, and `F5`
to sort; every control also works with a mouse.

The guided Python tools share that interface and remain useful directly:

```sh
bin/agent doctor
bin/disk health
bin/cleaner git audit
bin/hardware diagnose --area all
bin/security-audit audit --scope all --target .
bin/slurm plan --config slurm.toml
```

They use the Python standard library and native operating-system commands.
Read each adjacent `.help` page in the dashboard, or pass `--help` directly.
The [agent research](docs/agent-tools.md) records supported clients and cleanup
limits; the [security research](docs/security-research.md) explains scanner,
CVE, KEV, and host-check coverage; the
[Slurm example](docs/examples/slurm.toml) shows multi-job matrices.

Every runnable command under `bin`, `dev`, and `sys` has an adjacent Markdown
page. Fetch the same page without running its command by appending `.help`:

```sh
curl -fsSL \
  "https://raw.githubusercontent.com/keys-i/scripts/main/bin/disk.help"
```

The JSON front matter drives the dashboard; the Markdown below it remains
readable in a terminal. For styled output, pipe the same curl command to
[`glow -`](https://github.com/charmbracelet/glow).

Cleanup scripts always run a preview first. Applying repeats discovery with the
same settings and requires typing `CLEAN`, so targets can change if the
filesystem changes between the two runs.

To run one script directly without cloning or keeping a local copy:

```sh
(
  script='sys/linux/clean'
  tmp=$(mktemp) || exit 1
  trap 'rm -f "$tmp"' EXIT
  curl -fsSL \
    "https://raw.githubusercontent.com/keys-i/scripts/main/$script" \
    -o "$tmp" &&
    chmod +x "$tmp" &&
    "$tmp" --help
)
```

Change `script` to any path in this repository. The temporary file is removed
when the command finishes, and its shebang selects the right interpreter.

For PowerShell scripts:

```powershell
$script = 'sys/windows/clean.ps1'
$temp = Join-Path ([IO.Path]::GetTempPath()) "$([guid]::NewGuid()).ps1"
try {
    Invoke-WebRequest -UseBasicParsing `
        "https://raw.githubusercontent.com/keys-i/scripts/main/$script" `
        -OutFile $temp
    & $temp
} finally {
    Remove-Item $temp -Force -ErrorAction SilentlyContinue
}
```

Remote execution still fetches code temporarily, but none of these examples
leaves a repository or script behind. Review remote code before running it.

> [!CAUTION]
> Read system and cleanup scripts before running them. Use the least privilege
> needed and back up anything you cannot replace.

## File Structure

```sh
bin/  # Ready-to-run command-line tools
dev/  # Helpers for development, repositories, and local workflows
lib/  # Shared code used by more than one script
sys/  # OS maintenance, cleanup, and fixes
```

Scripts are grouped by purpose rather than programming language. Platform-
specific scripts can be placed below `sys/` when needed.

## Contributing

This is mainly my toolbox, but focused fixes and genuinely useful scripts are
welcome. Read the [contribution rules](docs/CONTRIBUTING.md) before opening a
pull request.

Please report security problems privately by following the
[security policy](docs/SECURITY.md).
