"""merge authenticate — get a magic link so a human can connect a connector."""

from __future__ import annotations

import re
import sys

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response

HINT = "Show this URL to your user, then retry the tool after they finish authenticating."

# The slug is interpolated into the meta-tool name sent to the server; keep it tight.
SLUG_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")


@click.command()
@click.argument("connector_slug")
def authenticate(
    connector_slug: str,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """Print a magic link that lets your user connect CONNECTOR_SLUG."""
    if not SLUG_PATTERN.fullmatch(connector_slug):
        emit(
            error_response(
                f"Invalid connector slug: {connector_slug!r}",
                error_type="invalid_params",
                hint="Connector slugs use lowercase letters, digits, hyphens, and underscores.",
            )
        )
        sys.exit(1)

    client, errors = get_client(
        api_key=api_key,
        tool_pack_id=tool_pack_id,
        registered_user_id=registered_user_id,
        base_url=base_url,
    )
    if errors or client is None:
        emit(config_error(errors))
        sys.exit(1)

    try:
        with client:
            raw_result = client.call_tool(f"authenticate_{connector_slug}", {})
            parsed = client.parse_tool_result(raw_result)
    except MergeClientError as exc:
        emit(error_response(str(exc), error_type="api_error"))
        sys.exit(1)
    except Exception as exc:
        emit(error_response(str(exc), error_type="network_error"))
        sys.exit(1)

    if parsed.get("status") != "success":
        emit(parsed)
        sys.exit(1)

    result = parsed.get("result")
    magic_link_url = result.get("magic_link_url") if isinstance(result, dict) else None
    if magic_link_url:
        emit(
            {
                "result": {"connector": connector_slug, "magic_link_url": magic_link_url},
                "status": "success",
                "hint": HINT,
            }
        )
    else:
        emit({**parsed, "hint": HINT})


authenticate = add_common_options(authenticate)
