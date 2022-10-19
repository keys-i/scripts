# Scripts

A home for the small scripts I keep reaching for.

Some came from HPC work, some fix annoying system problems, and others are
little command-line tools that save me from repeating the same steps. They live
here because they are useful, not because they need to become full projects.

## Using a Script

Run a script without cloning the repository or keeping a local copy:

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

Remote execution still fetches the script, but neither example leaves a copy
behind. Requirements differ between scripts; check the script before running
it and use its help text for supported systems and options.

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
[security policy](SECURITY.md).
