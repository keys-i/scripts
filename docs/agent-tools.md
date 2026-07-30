# AI agent CLI research

The `agent` command keeps a deliberately small local-state registry and uses
the live [Agent Skills CLI](https://github.com/vercel-labs/skills) for market
compatibility. No index can guarantee every public, private, or unpublished
skill. `agent market QUERY` searches the current indexed catalog, and
`agent market --install OWNER/REPOSITORY --agent NAME` asks the market tool to
apply its current client-specific installer.

## Safety contract

`agent clean` prefers documented vendor deletion commands. It directly removes
only narrow, documented memory, history, or cache paths below an agent's state
root. It does not remove authentication, settings, MCP configuration, plugins,
installed skills, or project instructions such as `AGENTS.md`, `CLAUDE.md`,
and `GEMINI.md`. The preview is the source of truth: close the selected agents,
inspect every target, then apply.

Directory symlinks are rejected so a declared glob cannot escape its state
root. Project-scoped Aider history is cleaned only from the current working
tree. Cloud-backed records are outside this command's authority: in particular,
local cleanup does not delete Copilot sessions already synced to GitHub or Amp
threads stored by its service.

## Researched clients

| Registry name    | Local cleanup                                                                                                                                                                                      | Doctor and market notes                                                                    |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `codex`          | Discovers saved UUIDs, then uses `codex delete UUID --force`; session cleanup also removes the documented global `history.jsonl`, while generated memories and caches remain separately selectable | Runs the redacted `codex doctor --json`; skills use `CODEX_HOME/skills`                    |
| `claude-code`    | `clean all` previews and runs `claude project purge --all`; the native command couples transcripts, auto-memory, and related project state                                                         | Honors `CLAUDE_CONFIG_DIR`; skills use its `skills` directory                              |
| `gemini-cli`     | Shows `gemini --list-sessions`; use `gemini --delete-session INDEX_OR_ID` because the list has no stable machine format                                                                            | `GEMINI.md`, settings, extensions, and skills remain untouched                             |
| `github-copilot` | Use the native interactive `/session` manager; managed command history and `session-store.db` are never removed                                                                                    | Synced session data may require deletion on GitHub                                         |
| `qwen-code`      | Conversation and memory cleanup is unsupported until a current native deletion contract is verified; cache remains selectable                                                                      | Doctor and indexed skills only                                                             |
| `opencode`       | Uses `opencode session list` and `session delete`; local logs are cache                                                                                                                            | Skills live in the XDG OpenCode configuration directory                                    |
| `kilo`           | No speculative database deletion                                                                                                                                                                   | Doctor and skill installation use `~/.kilocode`; use Kilo itself to delete conversations   |
| `cline`          | Use `cline history`; the managed SQLite session directory is never removed                                                                                                                         | Honors `CLINE_DATA_DIR`; logs remain separately selectable                                 |
| `aider`          | Current-project chat/input/LLM history and tags cache                                                                                                                                              | Aider does not natively load the shared Agent Skills format, so market install is rejected |
| `goose`          | Use `goose session list/remove`; `sessions.db` is never removed                                                                                                                                    | Honors `GOOSE_PATH_ROOT`; cache and logs remain separately selectable                      |
| `vibe`           | Automatic conversation and log cleanup is unsupported                                                                                                                                              | Market client identifier is `mistral-vibe`                                                 |
| `amp`            | Local logs only                                                                                                                                                                                    | Threads may be cloud-backed; shared skills use the agents skill directory                  |
| `cursor`         | No speculative editor database deletion                                                                                                                                                            | Doctor and Agent Skills support only                                                       |
| `kiro-cli`       | Automatic conversation cleanup is unsupported                                                                                                                                                      | Skills use `KIRO_HOME/skills`                                                              |
| `droid`          | No speculative service/database deletion                                                                                                                                                           | Doctor and Agent Skills support only                                                       |
| `openhands`      | No speculative service/database deletion                                                                                                                                                           | Doctor and Agent Skills support only                                                       |
| `pi`             | Automatic conversation cleanup is unsupported                                                                                                                                                      | Skills honor `PI_CODING_AGENT_DIR`                                                         |
| `rovodev`        | No speculative service/database deletion                                                                                                                                                           | Doctor and Agent Skills support only                                                       |

Clients without a documented, separable local conversation store intentionally
have no clean target. Deleting an entire application database just to remove
conversations would also destroy unrelated configuration and is not a safe
generic operation.

## Doctor

`agent doctor` finds each executable, runs its version command, checks known
JSON/TOML configuration syntax, reports state roots, and checks owner-only
permissions on Unix. Codex also runs its redacted native JSON doctor. YAML,
YAML-derived, and JSONC settings are reported as not parsed rather than
silently declared valid. `--fix` can create a missing skill directory or set a
known state root to mode `0700`; it does not reinstall a CLI, rewrite settings,
or invent vendor-specific repairs.

Environment overrides are evaluated every run:

- `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `COPILOT_HOME`, `CLINE_DATA_DIR`
- `GOOSE_PATH_ROOT`, `VIBE_HOME`, `KIRO_HOME`
- `PI_CODING_AGENT_DIR`
- `XDG_CONFIG_HOME` and `XDG_DATA_HOME` where the client follows XDG

## Market

The market is intentionally delegated to `npx skills` because its
compatibility map and repository catalog change independently of this
repository. Searching is interactive. An install previews the source's skills
first; `--apply` performs it, `--skill` narrows it, and `--global` selects user
scope. Skills may contain executable code, so review the repository and pinned
revision before installing. Set `DISABLE_TELEMETRY=1` if the Skills CLI's
documented anonymous telemetry is not wanted.

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
  [memory](https://geminicli.com/docs/tools/memory/),
  [Agent Skills](https://geminicli.com/docs/cli/using-agent-skills/), and
  [extensions](https://geminicli.com/docs/extensions/)
- GitHub Copilot CLI: [command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference),
  [configuration directories](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference),
  and [Chronicle](https://docs.github.com/en/enterprise-cloud@latest/copilot/concepts/agents/copilot-cli/chronicle)
- Qwen Code: [commands and sessions](https://qwenlm.github.io/qwen-code-docs/en/users/features/commands/)
  and [skills](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/)
- OpenCode: [CLI sessions](https://dev.opencode.ai/docs/cli/),
  [local data and troubleshooting](https://opencode.ai/docs/troubleshooting/),
  and [skills](https://opencode.ai/docs/skills/)
- Kilo Code: [skills](https://kilo.ai/docs/customize/skills) and
  [CLI](https://kilo.ai/cli)
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
- Cursor: [agent CLI](https://docs.cursor.com/en/cli/using)
- Kiro: [CLI skills](https://kiro.dev/docs/cli/skills/)
- Factory Droid: [skills](https://docs.factory.ai/cli/configuration/skills)
- OpenHands: [skills](https://docs.openhands.dev/overview/skills)
- Pi: [documentation](https://pi.dev/docs/latest)
- Atlassian Rovo Dev: [CLI commands](https://developer.atlassian.com/cloud/acli/reference/commands/rovodev/)
  and [skills](https://developer.atlassian.com/cloud/twg-cli/agents/skills/)

Storage layouts and commands can change between client releases. The table
describes the contract implemented here; a preview that differs from current
vendor documentation should not be applied.
