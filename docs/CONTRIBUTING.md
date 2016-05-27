# Contributing

This repository is a personal toolbox first, but useful fixes and scripts are
welcome. Keep contributions small enough to understand, test, and maintain.

## Before You Start

- Check that the script solves a real, repeatable problem.
- Search the repository before adding another version of an existing tool.
- Prefer the standard library and tools already available on the target system.
- Never include credentials, private data, machine-specific paths, or generated
  output.

## Branch Names

Use exactly this format:

```text
<action>/<short-kebab-summary>
```

Allowed actions are `add`, `fix`, `update`, `remove`, `docs`, `test`, and
`refactor`.

Good examples:

```text
add/slurm-job-summary
fix/macos-cache-cleanup
docs/explain-python-search
```

Branch names must be lowercase, use hyphens between words, and describe one
change. Names such as `work`, `changes`, `new-feature`, or `fix-stuff` will not
be accepted.

## Commit Messages

Use an allowed action, a colon, and a short summary:

```text
action: short line summary

Optional description explaining why the change was needed, any risks or
assumptions, and how it was tested.
```

Keep the first line at 72 characters or fewer. Write it as a command, without a
trailing full stop:

```text
add: find Python packages across common indexes
fix: preserve quoted arguments in cleanup script
```

Each commit should contain one logical change. No vague messages, merge noise,
or unrelated formatting changes.

## Script Standard

Only clean, understandable, and tested scripts are accepted.

- Put commands for users in `bin/`, development helpers in `dev/`, reusable
  code in `lib/`, and system maintenance in `sys/`.
- Include an appropriate shebang and make executable scripts executable.
- Validate input and fail with a useful message.
- Add comments where they explain intent, risk, or an unusual decision. Do not
  comment obvious syntax.
- Keep dependencies to the minimum and document every non-standard dependency.
- Make destructive behaviour explicit. Prefer a dry run or confirmation before
  deleting or overwriting data.
- Give every runnable script an adjacent `<script>.help` file. Start it with
  JSON front matter describing its platform and options, then write the actual
  help as concise Markdown. Destructive scripts must also declare matching
  `applyFlag` and `yesFlag` values; ordinary scripts omit both.
- Test the changed paths on every operating system or environment claimed by
  the script.
- Add the smallest repeatable test or self-check that would catch the bug
  returning. If automation is impractical, document the exact manual check.

When changing a script or its help page, also run the dashboard contract check:

```sh
dotnet run --project dev/tui -- --self-test
```

## Pull Requests

Open a focused pull request from your branch into `main`. Complete the template
and include:

- what changed and why;
- the exact commands or manual steps used to test it;
- the systems and interpreter versions tested;
- any destructive behaviour, elevated permissions, or known limitations.

A pull request is ready only when its scripts run successfully, its comments
and help text are current, and the diff contains no secrets or unrelated files.
All contributions must follow the [Code of Conduct](CODE_OF_CONDUCT.md).
