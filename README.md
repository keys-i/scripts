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

## Interactive Dashboard

The dashboard is useful when you do not remember every flag. It finds the
scripts for you, renders their help pages, guides you through their options,
and shows live output and progress. Cleanup scripts always preview first and
require `CLEAN` before applying.

It needs the
[.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0). This
macOS/Linux command runs a temporary copy and removes the source and package
cache when the dashboard closes:

```sh
(
  work=$(mktemp -d) || exit 1
  trap 'rm -rf "$work"' EXIT
  curl -fsSL \
    'https://github.com/keys-i/scripts/archive/refs/heads/main.tar.gz' |
    tar -xz -C "$work" --strip-components=1 &&
    DOTNET_CLI_HOME="$work/.dotnet" \
    NUGET_PACKAGES="$work/.nuget" \
    DOTNET_GENERATE_ASPNET_CERTIFICATE=false \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    dotnet run --project "$work/dev/tui" -- --root "$work"
)
```

On Windows PowerShell:

```powershell
$work = Join-Path ([IO.Path]::GetTempPath()) "scripts-$([guid]::NewGuid())"
$zip = "$work.zip"
$oldCliHome = $env:DOTNET_CLI_HOME
$oldPackages = $env:NUGET_PACKAGES
$oldCertificate = $env:DOTNET_GENERATE_ASPNET_CERTIFICATE
$oldTelemetry = $env:DOTNET_CLI_TELEMETRY_OPTOUT
$oldNoLogo = $env:DOTNET_NOLOGO
try {
    Invoke-WebRequest `
        'https://github.com/keys-i/scripts/archive/refs/heads/main.zip' `
        -OutFile $zip
    Expand-Archive $zip -DestinationPath $work
    $repo = Join-Path $work 'scripts-main'
    $env:DOTNET_CLI_HOME = Join-Path $work '.dotnet'
    $env:NUGET_PACKAGES = Join-Path $work '.nuget'
    $env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
    $env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
    $env:DOTNET_NOLOGO = '1'
    dotnet run --project (Join-Path $repo 'dev/tui') -- --root $repo
} finally {
    $env:DOTNET_CLI_HOME = $oldCliHome
    $env:NUGET_PACKAGES = $oldPackages
    $env:DOTNET_GENERATE_ASPNET_CERTIFICATE = $oldCertificate
    $env:DOTNET_CLI_TELEMETRY_OPTOUT = $oldTelemetry
    $env:DOTNET_NOLOGO = $oldNoLogo
    Remove-Item $work, $zip -Recurse -Force -ErrorAction SilentlyContinue
}
```

The dashboard starts full-screen. Add `--inline` after the final `--root`
argument to keep it in the terminal's normal scrollback. Use `F1` for help,
`F2` to run, and `F3` to filter; the same controls work with a mouse.

On Linux, run `sudo -v` before opening the dashboard if you plan to apply a
cleanup. Password prompts are disabled inside the TUI so they cannot interfere
with terminal input.

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
