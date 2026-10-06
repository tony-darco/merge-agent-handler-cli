[![PyPI version](https://img.shields.io/pypi/v/merge-api.svg)](https://pypi.org/project/merge-api/)
[![Python versions](https://img.shields.io/pypi/pyversions/merge-api.svg)](https://pypi.org/project/merge-api/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

# merge-cli

CLI for [Merge Agent Handler](https://merge.dev) — search, discover, and execute thousands of tools.

Designed for AI agents (Claude Code, Cursor) that need progressive tool discovery without clogging the context window.

## Install

```bash
pipx install merge-api   # recommended (isolated env)
pip install merge-api     # alternative
```

## Quick Start

### Option A: Login via browser (recommended)

```bash
merge login
```

Opens your browser to authenticate via OAuth. After consent, tokens are saved locally. No API key or tool pack ID needed.

### Option B: Configure with API key

> **Note:** `merge configure` is on a deprecation path. Use `merge login` instead.

```bash
merge configure
```

Or set environment variables:

```bash
export MERGE_AH_API_KEY="pk_..."
export MERGE_AH_TOOL_PACK_ID="your-tool-pack-uuid"
export MERGE_AH_REGISTERED_USER_ID="your-registered-user-id"
```

### 2. Search for tools

```bash
merge search-tools "send a Slack message"
```

```json
{
  "tools": [
    {
      "name": "slack__post_message",
      "description": "Post a message to a Slack channel",
      "input_schema": { "type": "object", "properties": { "channel": { "type": "string" }, "text": { "type": "string" } } },
    }
  ],
  "total_results": 1,
  "hint": "To execute: merge execute-tool <tool_name> '<json_params>'"
}
```

### 3. Execute a tool

```bash
merge execute-tool slack__post_message '{"input": {"channel": "#general", "text": "Hello!"}}'
```

```json
{
  "result": { "ok": true, "ts": "1234567890.123456" },
  "status": "success",
  "hint": "Tool executed successfully."
}
```

## Commands

| Command | Description |
|---|---|
| `merge search-tools <intent>` | Semantic search for tools by natural language (returns compact schemas) |
| `merge execute-tool <tool> <params>` | Execute a tool with JSON parameters |
| `merge list-tools` | List all available tools (compact by default) |
| `merge get-tool-schema <tool>` | Get the input schema for a specific tool |
| `merge login` | Log in via browser (OAuth) |
| `merge logout` | Log out and clear OAuth tokens |
| `merge configure` | Interactive API key setup (on deprecation path — use `merge login`) |
| `merge setup <target>` | Generate AI agent config (claude-code, cursor, agents-md) |
| `merge update` | Self-update to latest version |

### Common Options

All API commands accept these flags:

| Flag | Env Variable | Description |
|---|---|---|
| `--api-key` | `MERGE_AH_API_KEY` | API key |
| `--tool-pack-id` | `MERGE_AH_TOOL_PACK_ID` | Tool pack ID |
| `--registered-user-id` | `MERGE_AH_REGISTERED_USER_ID` | Registered user ID |

| `--base-url` | `MERGE_AH_BASE_URL` | Base URL override |

## Authentication

Two auth modes, auto-detected:

| Mode | Setup | Endpoint | Use case |
|------|-------|----------|----------|
| **OAuth** (recommended) | `merge login` | `/mcp/` | Human users, interactive |
| **API key** | `merge configure` | `/api/v1/tool-packs/.../mcp` | CI/CD, automation |

If both are configured, OAuth takes priority.

## Configuration

Priority (highest to lowest):

1. **CLI flags**: `--api-key`, `--tool-pack-id`, `--registered-user-id`, `--base-url`
2. **Environment variables**: `MERGE_AH_API_KEY`, `MERGE_AH_TOOL_PACK_ID`, `MERGE_AH_REGISTERED_USER_ID`, `MERGE_AH_BASE_URL`
3. **Config file**: `~/.merge/config.json`

Example config file:

```json
{
  "agent_handler": {
    "api_key": "pk_...",
    "tool_pack_id": "your-tool-pack-uuid",
    "registered_user_id": "your-registered-user-id"
  },
  "oauth": {
    "access_token": "...",
    "refresh_token": "...",
    "client_id": "merge-cli"
  }
}
```

## Output Format

All commands output JSON to stdout. Warnings go to stderr.

**Success response:**

```json
{
  "result": { ... },
  "status": "success",
  "hint": "Tool executed successfully."
}
```

**Error response:**

```json
{
  "result": null,
  "status": "error",
  "error_type": "api_error",
  "message": "Description of what went wrong",
  "hint": "Suggested next step"
}
```

Error types: `config_error`, `api_error`, `network_error`, `invalid_params`, `not_found`, `reauth_required`, `billing_limit_reached`

## Usage with AI Agents

The fastest way to set up any AI agent is the `merge setup` command:

### Claude Code

```bash
merge setup claude-code
```

This appends merge CLI instructions to your `CLAUDE.md` (or creates it if it doesn't exist) and adds `Bash(merge *)` to `.claude/settings.json`. Safe to run multiple times — it won't duplicate content.

### Cursor

```bash
merge setup cursor
```

This appends merge CLI instructions to your `.cursorrules` (or creates it if it doesn't exist).

### Any AI Agent (AGENTS.md)

```bash
merge setup agents-md
```

This appends merge CLI instructions to your `AGENTS.md` (or creates it if it doesn't exist) — the cross-tool standard supported by Claude Code, Cursor, Codex, Windsurf, and more.

### Manual Setup

If you prefer manual configuration, add this to your agent's system prompt or project instructions:

```
For any task involving third-party services (Slack, Jira, GitHub, Salesforce, etc.),
use the `merge` CLI. Do not call APIs directly.

Workflow:
1. merge search-tools "<intent>"        — find tools (returns compact schemas)
2. merge execute-tool <tool> '<json>'   — execute with JSON params
```

## Troubleshooting

| Problem | Solution |
|---|---|
| `config_error` | Run `merge login` (or `merge configure` for API key auth) |
| `api_error` with 401 | Check your API key. Ensure test keys are used with test users and production keys with production users |
| `not_found` | Use `merge search-tools <intent>` or `merge list-tools` to discover available tools |
| `reauth_required` | The user needs to re-authenticate the connector in the Merge dashboard |
| `billing_limit_reached` | Upgrade the account at the billing URL in the error response |
| `network_error` | Check your internet connection and `--base-url` setting |

## Development

```bash
git clone https://github.com/merge-api/merge-cli.git
cd merge-cli
pip install -e ".[dev]"
pytest                    # run tests
ruff check .              # lint
ruff format --check .     # format check
```

## License

[MIT](LICENSE)
