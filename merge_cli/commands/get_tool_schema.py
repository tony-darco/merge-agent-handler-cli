"""merge get-tool-schema — get the input schema for a single tool."""

from __future__ import annotations

import sys

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response


@click.command()
@click.argument("tool_name")
def get_tool_schema(
    tool_name: str,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """Get the full input schema for TOOL_NAME."""
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
            tool = client.get_tool_schema(tool_name)
    except MergeClientError as exc:
        emit(error_response(str(exc), error_type="api_error"))
        sys.exit(1)
    except Exception as exc:
        emit(error_response(str(exc), error_type="network_error"))
        sys.exit(1)

    if tool is None:
        emit(
            error_response(
                f"Tool '{tool_name}' not found.",
                error_type="not_found",
                hint=(
                    "Use 'merge search-tools <intent>' or 'merge list-tools'"
                    " to find available tools."
                ),
            )
        )
        sys.exit(1)

    emit(
        {
            "name": tool.get("name", tool_name),
            "description": tool.get("description", ""),
            "input_schema": tool.get("inputSchema", {}),
            "hint": f"To execute: merge execute-tool {tool_name} '<json_params>'",
        }
    )


get_tool_schema = add_common_options(get_tool_schema)
