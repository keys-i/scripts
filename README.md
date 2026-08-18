# Scripts

A home for the small scripts I keep reaching for.

Some came from HPC work, some fix annoying system problems, and others are
little command-line tools that save me from repeating the same steps. They live
here because they are useful, not because they need to become full projects.

## Using a Script

Run the collection without cloning or installing it:

```sh
curl -fsSL https://github.com/keys-i/scripts/raw/refs/heads/main/run.sh | bash
```

The `/blob/` URL is a web page and cannot be piped to a shell. The `/raw/`
endpoint above downloads one temporary source archive, opens the responsive
dashboard when `uv` and a terminal are available, and removes the archive when
the selected command exits. Streamed use needs `curl`, `tar`, and either Python
3.11+ or [`uv`](https://docs.astral.sh/uv/getting-started/installation/). On
Windows, use Git Bash with native Windows Python or `uv`; WSL runs the Linux
catalog instead.

The same entry point lists scripts, renders any adjacent `.man` page, or runs a
command directly:

```sh
RUN=https://github.com/keys-i/scripts/raw/refs/heads/main/run.sh
curl -fsSL "$RUN" | bash -s -- list
curl -fsSL "$RUN" | bash -s -- matrix
curl -fsSL "$RUN" | bash -s -- man disk
curl -fsSL "$RUN" | bash -s -- disk health
curl -fsSL "$RUN" | bash -s -- security-audit audit --scope system
curl -fsSL "$RUN" | bash -s -- slurm plan slurm.toml
```

`man SCRIPT` uses Glow when available and otherwise prints plain Markdown. The
same manuals drive the dashboard, so there is no second help source to drift.
From a local checkout, use the shorter equivalents:

```sh
./run.sh
./run.sh list
./run.sh matrix
./run.sh man disk
./run.sh clean
./run.sh fetch --plain
./run.sh games list --json
./run.sh science snapshot orbit --json
```

Cleanup scripts always preview first and require explicit confirmation before
applying changes. `cleaner dev --root ~/Coding` inventories manifest-backed
build output, dependency trees, and language caches before offering removal.
The [agent research](docs/agent-tools.md) records supported
clients and cleanup limits; the [security research](docs/security-research.md)
explains scanner, CVE, KEV, and host-check coverage; the
[Slurm example](examples/slurm.toml) shows every resource and command option.

Remote execution still runs mutable code from `main`; review it before use or
replace `main` with a trusted commit SHA.

> [!CAUTION]
> Read system and cleanup scripts before running them. Use the least privilege
> needed and back up anything you cannot replace.

## File Structure

```sh
bin/  # Ready-to-run command-line tools
dev/  # Helpers for development, repositories, and local workflows
lib/  # Shared code used by more than one script
sys/  # OS maintenance, cleanup, and fixes
packs/ # Typed manuals for optional external executables; no wrapper logic
```

Scripts are grouped by purpose rather than programming language. Platform-
specific scripts can be placed below `sys/` when needed. A `packs/NAME.man`
manual may declare `"executable": "NAME"` to expose one installed external
tool through the same launcher and dashboard without duplicating it in Bash or
Python. Missing executables fail with an install hint; packs never download
software implicitly.

## Contributing

This is mainly my toolbox, but focused fixes and genuinely useful scripts are
welcome. Read the [contribution rules](docs/CONTRIBUTING.md) before opening a
pull request.

Please report security problems privately by following the
[security policy](docs/SECURITY.md).
