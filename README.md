# Scripts

A home for the small scripts I keep reaching for.

Some came from HPC work, some fix annoying system problems, and others are
little command-line tools that save me from repeating the same steps. They live
here because they are useful, not because they need to become full projects.

## Using a Script

Clone the repository, read the script, then run it directly or place it on your
`PATH`:

```sh
git clone https://github.com/keys-i/scripts.git
cd scripts
./bin/<script> --help
```

Requirements differ between scripts. Each script should explain its
dependencies and supported systems in its help text or header.

> [!CAUTION]
> Read system and cleanup scripts before running them. Use the least privilege
> needed and back up anything you cannot replace.

## File Structure

```text
bin/  Ready-to-run command-line tools.
dev/  Helpers for development, repositories, and local workflows.
lib/  Shared code used by more than one script.
sys/  Operating-system maintenance, cleanup, and fixes.
```

Scripts are grouped by purpose rather than programming language. Platform-
specific scripts can be placed below `sys/` when needed.

## Contributing

This is mainly my toolbox, but focused fixes and genuinely useful scripts are
welcome. Read the [contribution rules](docs/CONTRIBUTING.md) before opening a
pull request.

Please report security problems privately by following the
[security policy](SECURITY.md).
