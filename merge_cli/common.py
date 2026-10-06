"""Shared Click options and helpers for commands that require authentication."""

from __future__ import annotations

import click

from merge_cli.client import MergeClient
from merge_cli.config import load_ah_config, load_oauth_config, validate_base_url

COMMON_OPTIONS = [
    click.option("--api-key", envvar="MERGE_AH_API_KEY", default=None, help="API key override."),
    click.option(
        "--tool-pack-id", envvar="MERGE_AH_TOOL_PACK_ID", default=None, help="Tool pack ID."
    ),
    click.option(
        "--registered-user-id",
        envvar="MERGE_AH_REGISTERED_USER_ID",
        default=None,
        help="Registered user ID.",
    ),
    click.option("--base-url", envvar="MERGE_AH_BASE_URL", default=None, help="Base URL override."),
]


def add_common_options(cmd):
    """Apply shared auth/config options to a command."""
    for option in reversed(COMMON_OPTIONS):
        cmd = option(cmd)
    return cmd


def get_client(
    api_key: str | None = None,
    tool_pack_id: str | None = None,
    registered_user_id: str | None = None,
    base_url: str | None = None,
):
    """Create a MergeClient using auto-detected auth mode.

    Priority: OAuth token > API key.
    Returns (client, errors) — errors is empty list if auth is valid.
    """
    # Try OAuth first
    oauth_cfg = load_oauth_config(base_url=base_url)
    if oauth_cfg is not None:
        errors = oauth_cfg.validate()
        if not errors:
            url_error = validate_base_url(oauth_cfg.base_url)
            if url_error:
                return None, [url_error]
            return MergeClient(oauth_config=oauth_cfg), []

    # Fall back to API key
    ah_cfg = load_ah_config(
        api_key=api_key,
        tool_pack_id=tool_pack_id,
        registered_user_id=registered_user_id,
        base_url=base_url,
    )
    errors = ah_cfg.validate()
    if not errors:
        url_error = validate_base_url(ah_cfg.base_url)
        if url_error:
            return None, [url_error]
        return MergeClient(config=ah_cfg), []

    return None, ["Not authenticated. Run `merge agent signup` (agents) or `merge login` (humans)."]
