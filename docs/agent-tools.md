# AI agent CLI research

The `agent` command keeps a deliberately small local-state registry and uses
the live [Agent Skills CLI](https://github.com/vercel-labs/skills) for market
compatibility. No index can guarantee every public, private, or unpublished
skill. `agent market QUERY` searches the current indexed catalog, and
`agent market --install OWNER/REPOSITORY --agent NAME` asks the market tool to
apply its current client-specific installer.

Contracts and links were reviewed against official vendor documentation on
31 July 2026 (Australia/Brisbane).

## Safety contract

`agent clean` prefers documented vendor deletion commands. It directly removes
only narrow, documented memory, history, or cache paths below an agent's state
root. It does not remove authentication, settings, MCP configuration, plugins,
installed skills, or project instructions such as `AGENTS.md`, `CLAUDE.md`,
and `GEMINI.md`. The preview is the source of truth: close the selected agents,
inspect every target, then apply. It reports local entry counts and logical
bytes without following symlinks; native operations have no preflight size.

Directory symlinks are rejected so a declared glob cannot escape its state
root. Project-scoped Aider history is cleaned only from the current working
tree. Cloud-backed records are outside this command's authority: in particular,
local cleanup does not delete Copilot sessions already synced to GitHub or Amp
threads stored by its service.

Direct path removal is local only. Native commands are invoked without remote
flags and retain their vendor-defined local scope. The script never signs into
a provider to erase account, cloud, synchronized, Hub, IDE, or retention
records. `market` is the only intentionally networked workflow.

## Researched clients

| Registry name    | Local cleanup                                                                                                                                                      | Doctor and market notes                                                                      |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| `codex`          | Discovers saved UUIDs, then uses local `codex delete UUID --force`; session cleanup also removes `history.jsonl`; memories and caches remain separately selectable | Honors `CODEX_HOME`; runs redacted `codex doctor --json`; skills use its `skills` directory  |
| `claude-code`    | `clean all` previews and runs local `claude project purge --all`; the command couples transcripts, auto-memory, and related project state                          | Honors `CLAUDE_CONFIG_DIR`; web, desktop, and IDE histories are separate                     |
| `gemini-cli`     | Shows current-project `gemini --list-sessions`; use `gemini --delete-session INDEX_OR_ID`; default retention is 30 days                                            | Honors `GEMINI_CLI_HOME` as the parent of `.gemini`; skills and settings remain untouched    |
| `github-copilot` | Use `/session delete ID --yes`, `/session delete-all --yes`, or preview `/session prune --older-than DAYS --dry-run`; the managed database is never removed        | Bulk/prune deletion is local; synced copies require GitHub or a prompted single deletion     |
| `qwen-code`      | Use `qwen sessions list --json` and interactive `/delete`, `/forget`, or `/memory`; there is no documented noninteractive delete-all contract                      | Honors `QWEN_HOME`; separate `QWEN_RUNTIME_DIR` output remains outside automatic cleanup     |
| `opencode`       | Uses `opencode session list` and `session delete`; local logs are cache                                                                                            | Skills live in the XDG OpenCode configuration directory                                      |
| `kilo`           | Uses `kilo session list --all --format json` and `kilo session delete ID`; Cloud Agent sessions remain separate                                                    | Runs `kilo config check`; data uses the platform data directory; skills use `~/.kilo/skills` |
| `cline`          | Use `cline history`; the managed SQLite session directory is never removed                                                                                         | Honors `CLINE_DATA_DIR`; Cline Hub and remote backends are outside local cleanup             |
| `aider`          | Current-project chat/input/LLM history and tags cache                                                                                                              | Aider does not natively load the shared Agent Skills format, so market install is rejected   |
| `goose`          | Use native `goose session` management; `sessions.db` is never removed                                                                                              | Unix sessions use XDG data, Windows uses `%APPDATA%`; Unix logs remain outside cleanup       |
| `vibe`           | Automatic conversation and log cleanup is unsupported                                                                                                              | Market client identifier is `mistral-vibe`                                                   |
| `amp`            | Local logs only                                                                                                                                                    | Threads may be cloud-backed; shared skills use the agents skill directory                    |
| `cursor`         | No speculative editor database deletion                                                                                                                            | Official Agent Skills support includes shared `.agents/skills` locations                     |
| `kiro-cli`       | Automatic conversation cleanup is unsupported                                                                                                                      | Skills use `KIRO_HOME/skills`                                                                |
| `droid`          | No speculative service/database deletion                                                                                                                           | Factory Cloud Sync may retain a web copy; native skills/plugins stay vendor-managed          |
| `openhands`      | Removes documented local `~/.openhands/conversations/*` directories                                                                                                | OpenHands Cloud is separate; native Windows requires WSL; skills stay untouched              |
| `pi`             | Removes documented local session JSONL files without following symlinks                                                                                            | Honors `PI_CODING_AGENT_DIR` and `PI_CODING_AGENT_SESSION_DIR`; skills stay untouched        |
| `rovodev`        | Use the interactive `/sessions` menu (`d`, then Enter) for deletion                                                                                                | Sessions are workspace-scoped under `~/.rovodev/sessions`; skills stay vendor-managed        |

Clients without a documented, separable local conversation store intentionally
have no clean target. Deleting an entire application database just to remove
conversations would also destroy unrelated configuration and is not a safe
generic operation.

## Doctor

`agent doctor` finds each executable, runs its version command, checks known
JSON/TOML configuration syntax, reports state roots, and checks owner-only
permissions on Unix. Codex also runs its redacted native JSON doctor. YAML,
YAML-derived, and JSONC settings are reported as not parsed rather than
silently declared valid. Kilo also runs `kilo config check`. A missing binary
with remaining state is distinguished from an installed but uninitialized
client. `--fix` can set a known state root to mode `0700`; it does not create
installer-owned skill directories, reinstall a CLI, rewrite settings, or
invent vendor-specific repairs.

Environment overrides are evaluated every run:

- `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `GEMINI_CLI_HOME`, `COPILOT_HOME`
- `QWEN_HOME`, `QWEN_RUNTIME_DIR`, `CLINE_DATA_DIR`
- `GOOSE_PATH_ROOT`, `VIBE_HOME`, `KIRO_HOME`
- `PI_CODING_AGENT_DIR`, `PI_CODING_AGENT_SESSION_DIR`
- `XDG_CONFIG_HOME` and `XDG_DATA_HOME` where the client follows XDG

## Market

The market is intentionally delegated to `npx skills` because its
compatibility map and repository catalog change independently of this
repository. Searching is interactive. An install previews the source's skills
first; `--apply` performs it, `--skill` narrows it, and `--global` selects user
scope. Skills may contain executable code, so review the repository and pinned
revision before installing. Set `DISABLE_TELEMETRY=1` if the Skills CLI's
documented anonymous telemetry is not wanted.

Compatibility was refreshed from the live Skills CLI support table on the
review date. All registry clients except Aider currently have a market client
identifier. `agent doctor --list-agents` reports `skills` or `unsupported`
directly from that registry rather than maintaining a second compatibility
database.

## Primary references

- OpenAI Codex: [CLI reference](https://developers.openai.com/codex/cli/reference),
  [memories](https://learn.chatgpt.com/docs/customization/memories),
  [plugins](https://developers.openai.com/codex/plugins), and the
  [open-source CLI](https://github.com/openai/codex)
- Claude Code: [session management](https://code.claude.com/docs/en/sessions),
  [memory](https://code.claude.com/docs/en/memory),
  [configuration directories](https://code.claude.com/docs/en/claude-directory),
  and [plugins](https://code.claude.com/docs/en/discover-plugins)
- Gemini CLI: [session management](https://geminicli.com/docs/cli/session-management/),
  [enterprise home override](https://geminicli.com/docs/cli/enterprise/),
  [memory](https://geminicli.com/docs/tools/memory/),
  [Agent Skills](https://geminicli.com/docs/cli/using-agent-skills/), and
  [extensions](https://geminicli.com/docs/extensions/)
- GitHub Copilot CLI: [command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference),
  [configuration directories](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference),
  and [Chronicle](https://docs.github.com/en/enterprise-cloud@latest/copilot/concepts/agents/copilot-cli/chronicle)
- Qwen Code: [commands and sessions](https://qwenlm.github.io/qwen-code-docs/en/users/features/commands/),
  [memory](https://qwenlm.github.io/qwen-code-docs/en/users/features/memory/),
  [settings](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/),
  and [skills](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/)
- OpenCode: [CLI sessions](https://dev.opencode.ai/docs/cli/),
  [local data and troubleshooting](https://opencode.ai/docs/troubleshooting/),
  and [skills](https://opencode.ai/docs/skills/)
- Kilo Code: [CLI reference](https://kilo.ai/docs/code-with-ai/platforms/cli-reference),
  [data locations](https://kilo.ai/docs/getting-started/settings/sandboxing),
  and [skills](https://kilo.ai/docs/customize/skills)
- Cline: [CLI reference](https://docs.cline.bot/cli/cli-reference),
  [data architecture](https://docs.cline.bot/sdk/architecture/hub-spoke), and
  [skills](https://docs.cline.bot/customization/skills)
- Aider: [configuration](https://aider.chat/docs/config/aider_conf.html)
- goose: [CLI session commands](https://goose-docs.ai/docs/guides/goose-cli-commands/)
  and [logs/session data](https://goose-docs.ai/docs/guides/logs/)
- Mistral Vibe: [configuration](https://docs.mistral.ai/vibe/code/cli/configuration),
  [CLI workflow](https://docs.mistral.ai/vibe/code/cli/work-with-cli), and
  [skills](https://docs.mistral.ai/vibe/code/cli/skills)
- Amp: [manual](https://ampcode.com/manual)
- Cursor: [agent CLI](https://docs.cursor.com/en/cli/using) and
  [skills](https://cursor.com/docs/skills)
- Kiro: [CLI skills](https://kiro.dev/docs/cli/skills/)
- Factory Droid: [settings and Cloud Sync](https://docs.factory.ai/cli/configuration/settings)
  and [skills](https://docs.factory.ai/cli/configuration/skills)
- OpenHands: [local conversations](https://docs.openhands.dev/openhands/usage/cli/resume)
  and [skills](https://docs.openhands.dev/overview/skills/adding)
- Pi: [sessions](https://pi.dev/docs/latest/sessions),
  [session format](https://pi.dev/docs/latest/session-format), and
  [skills](https://pi.dev/docs/latest/skills)
- Atlassian Rovo Dev: [session management](https://support.atlassian.com/rovo/docs/manage-sessions-in-rovo-dev-cli/)
  and [skills](https://support.atlassian.com/rovo/docs/extend-rovo-dev-cli-with-agent-skills/)

Storage layouts and commands can change between client releases. The table
describes the contract implemented here; a preview that differs from current
vendor documentation should not be applied.
