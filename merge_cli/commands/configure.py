"""merge configure — interactive setup for ~/.merge/config.json."""

from __future__ import annotations

import click

from merge_cli.config import (
    DEFAULT_BASE_URL,
    AgentHandlerConfig,
    _load_config_file,
    save_ah_config,
)


@click.command(deprecated=True)
def configure():
    """Interactive setup — prompts for Agent Handler credentials.

    DEPRECATED: Use `merge login` instead for OAuth-based authentication.
    """
    click.echo(
        click.style(
            "Warning: `merge configure` is on a deprecation path. Use `merge login` instead.",
            fg="yellow",
        )
    )
    click.echo()
    existing = _load_config_file()
    ah = existing.get("agent_handler", {})

    click.echo("Merge CLI Configuration")
    click.echo("=" * 40)
    click.echo("\nAgent Handler settings:\n")

    api_key = click.prompt(
        "  API Key (ProductionKey)",
        default=ah.get("api_key", ""),
        show_default=bool(ah.get("api_key")),
    )
    tool_pack_id = click.prompt(
        "  Tool Pack ID",
        default=ah.get("tool_pack_id", ""),
        show_default=bool(ah.get("tool_pack_id")),
    )
    registered_user_id = click.prompt(
        "  Registered User ID (UUID or origin_id)",
        default=ah.get("registered_user_id", ""),
        show_default=bool(ah.get("registered_user_id")),
    )
    base_url = click.prompt(
        "  Base URL",
        default=ah.get("base_url", DEFAULT_BASE_URL),
    )

    save_ah_config(
        AgentHandlerConfig(
            api_key=api_key,
            tool_pack_id=tool_pack_id,
            registered_user_id=registered_user_id,
            base_url=base_url,
        )
    )
    click.echo("\nConfiguration saved to ~/.merge/config.json")
