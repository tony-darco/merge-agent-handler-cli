"""merge setup — generate AI agent configuration files."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from merge_cli.config import load_ah_config, load_oauth_config
from merge_cli.output import warn

CLAUDE_MD_SECTION = """## Merge CLI

For any task involving third-party services, you MUST use the `merge` CLI.
Do NOT attempt to call APIs directly, use other tools, or guess endpoints.

### Commands

- `merge search-tools "<intent>"` — Search for tools. Returns compact input schemas.
- `merge execute-tool <tool_name> '<json_params>'` — Execute a tool.

### Workflow

**Step 1 — Find ALL tools you need in one batch.** In your first response, run parallel searches for every tool you'll need:
```
merge search-tools "create task" --connector asana    # main action
merge search-tools "list workspaces" --connector asana # lookup tool
merge search-tools "list users" --connector asana      # another lookup
```
Run ALL searches in parallel in one response.

**Step 2 — Execute lookups in parallel**, then execute the main tool.

Do NOT call `merge get-tool-schema`. Search returns schemas. Pass null for optional params you don't need.

### Authentication

- If every command fails with `config_error` ("Not authenticated"), ask the user to run `merge login` — it opens their browser. You cannot log in for them.
- If a tool call fails with an authentication error, that connector is not connected yet. Run `merge authenticate <connector>` (e.g. `merge authenticate notion`) — it returns a magic link. Share the link with the user, wait for them to connect, then retry the tool.

### Rules

- Tool names: `<connector>__<action>` (except authentication tools, named `authenticate_<connector>`).
- ALWAYS run independent Bash calls in parallel.
- If you don't know the connector, search without --connector first.
"""

AGENTS_MD_SECTION = """## Merge CLI

For any task involving third-party services, use the `merge` CLI.

### Commands

- `merge search-tools "<intent>"` — Search for tools (returns compact schemas)
- `merge execute-tool <tool_name> '<json_params>'` — Execute a tool

### Workflow

1. Search for ALL tools you need in parallel: run multiple `merge search-tools` calls simultaneously.
2. Execute lookups in parallel, then execute the main tool.

Always search before executing. Never guess tool names. Pass null for optional params.

### Authentication

- If every command fails with `config_error` ("Not authenticated"), ask the user to run `merge login` — it opens their browser. You cannot log in for them.
- If a tool call fails with an authentication error, that connector is not connected yet. Run `merge authenticate <connector>` (e.g. `merge authenticate notion`) — it returns a magic link. Share the link with the user, wait for them to connect, then retry the tool.
"""

CLAUDE_SETTINGS_PERMISSION = "Bash(merge *)"

SETUP_TARGETS = ["claude-code", "cursor", "agents-md"]


def detect_host() -> str:
    """Pick the setup target from the env vars the agent hosts set."""
    if os.environ.get("CLAUDECODE"):
        return "claude-code"
    if os.environ.get("CURSOR_TRACE_ID"):
        return "cursor"
    return "agents-md"


def _write_text(path: Path, content: str) -> bool:
    """Refuse to write through a symlink — a planted link could redirect the write anywhere."""
    if path.is_symlink():
        warn(f"{path} is a symlink — skipping this write.")
        return False
    path.write_text(content)
    return True


def run_setup(target: str, project: Path) -> None:
    if target == "claude-code":
        _setup_claude_code(project)
    elif target == "cursor":
        _setup_cursor(project)
    elif target == "agents-md":
        _setup_agents_md(project)


@click.command()
@click.argument(
    "target",
    type=click.Choice(SETUP_TARGETS, case_sensitive=False),
    required=False,
)
@click.option(
    "--project-dir",
    default=".",
    type=click.Path(exists=True, file_okay=False),
    help="Project directory (default: current directory).",
)
def setup(target: str | None, project_dir: str):
    """Generate AI agent configuration for TARGET.

    Supported targets: claude-code, cursor, agents-md. Without TARGET the host is
    detected from the environment (Claude Code, Cursor, else AGENTS.md).
    """
    if target is None:
        target = detect_host()
        click.echo(f"Detected host: {target}")

    run_setup(target, Path(project_dir).resolve())


def _setup_claude_code(project: Path) -> None:
    """Generate CLAUDE.md section and .claude/settings.json permission."""
    # Update or create CLAUDE.md
    claude_md = project / "CLAUDE.md"
    marker = "## Merge CLI"

    if claude_md.exists():
        content = claude_md.read_text()
        if marker in content:
            click.echo("CLAUDE.md already contains Merge CLI instructions — skipping.")
        elif _write_text(claude_md, content.rstrip() + "\n\n" + CLAUDE_MD_SECTION):
            click.echo(f"Appended Merge CLI instructions to {claude_md}")
    elif _write_text(claude_md, CLAUDE_MD_SECTION):
        click.echo(f"Created {claude_md}")

    # Update or create .claude/settings.json
    settings_dir = project / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_file = settings_dir / "settings.json"

    settings: dict | None = {}
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError:
            settings = None
        if not isinstance(settings, dict):
            # Never overwrite a file we can't parse — the user would silently lose it.
            warn(f"{settings_file} is not valid JSON — skipping the permissions update.")
            settings = None

    if settings is not None:
        permissions = settings.setdefault("permissions", {})
        allow_list = permissions.setdefault("allow", [])

        if CLAUDE_SETTINGS_PERMISSION in allow_list:
            click.echo(f"'{CLAUDE_SETTINGS_PERMISSION}' already in {settings_file} — skipping.")
        else:
            allow_list.append(CLAUDE_SETTINGS_PERMISSION)
            if _write_text(settings_file, json.dumps(settings, indent=2) + "\n"):
                click.echo(f"Added '{CLAUDE_SETTINGS_PERMISSION}' to {settings_file}")

    # Check if credentials are configured (OAuth preferred, API key fallback)
    oauth_cfg = load_oauth_config()
    if oauth_cfg is not None and not oauth_cfg.validate():
        pass  # OAuth is configured and valid
    else:
        ah_cfg = load_ah_config()
        if ah_cfg.validate():
            warn("Not authenticated. Run `merge agent signup` (agents) or `merge login` (humans).")

    click.echo(
        "\nSetup complete! Claude Code will now use the merge CLI for third-party service tasks."
    )


def _setup_cursor(project: Path) -> None:
    """Generate .cursorrules with merge CLI instructions."""
    rules_file = project / ".cursorrules"
    marker = "## Merge CLI"

    content = AGENTS_MD_SECTION  # Same format works for Cursor

    if rules_file.exists():
        existing = rules_file.read_text()
        if marker in existing:
            click.echo(".cursorrules already contains Merge CLI instructions — skipping.")
            return
        if _write_text(rules_file, existing.rstrip() + "\n\n" + content):
            click.echo(f"Appended Merge CLI instructions to {rules_file}")
    elif _write_text(rules_file, content):
        click.echo(f"Created {rules_file}")

    click.echo("\nSetup complete! Cursor will now use the merge CLI for third-party service tasks.")


def _setup_agents_md(project: Path) -> None:
    """Generate AGENTS.md with merge CLI instructions."""
    agents_md = project / "AGENTS.md"
    marker = "## Merge CLI"

    if agents_md.exists():
        content = agents_md.read_text()
        if marker in content:
            click.echo("AGENTS.md already contains Merge CLI instructions — skipping.")
            return
        if _write_text(agents_md, content.rstrip() + "\n\n" + AGENTS_MD_SECTION):
            click.echo(f"Appended Merge CLI instructions to {agents_md}")
    elif _write_text(agents_md, AGENTS_MD_SECTION):
        click.echo(f"Created {agents_md}")

    click.echo(
        "\nSetup complete! AI agents that support AGENTS.md will now discover the merge CLI."
    )
