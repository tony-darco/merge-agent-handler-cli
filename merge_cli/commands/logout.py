"""merge logout — clear OAuth tokens."""

from __future__ import annotations

import click
import httpx

from merge_cli.config import clear_oauth_config, load_oauth_config


@click.command()
def logout():
    """Log out — revoke and clear stored OAuth tokens."""
    oauth_cfg = load_oauth_config()

    if oauth_cfg is None:
        click.echo("Not logged in.")
        return

    # Try to revoke the token on the server
    if oauth_cfg.access_token:
        try:
            httpx.post(
                f"{oauth_cfg.base_url}/o/revoke_token/",
                data={
                    "token": oauth_cfg.access_token,
                    "client_id": oauth_cfg.client_id,
                },
                timeout=5.0,
            )
        except Exception:
            pass  # Best-effort revocation

    clear_oauth_config()
    click.echo("Logged out. OAuth tokens cleared.")
