"""merge execute-tool — execute a tool with JSON parameters."""

from __future__ import annotations

import json
import sys

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response


@click.command()
@click.argument("tool_name")
@click.argument("params_json")
def execute_tool(
    tool_name: str,
    params_json: str,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """Execute TOOL_NAME with PARAMS_JSON arguments."""
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
        arguments = json.loads(params_json)
    except json.JSONDecodeError as exc:
        emit(
            error_response(
                f"Invalid JSON parameters: {exc}",
                error_type="invalid_params",
                hint=(
                    "Parameters must be valid JSON. Example: "
                    '\'{"input": {"channel": "#general", "text": "Hello"}}\''
                ),
            )
        )
        sys.exit(1)

    try:
        with client:
            raw_result = client.call_tool(tool_name, arguments)
            parsed = client.parse_tool_result(raw_result)
    except MergeClientError as exc:
        emit(error_response(str(exc), error_type="api_error"))
        sys.exit(1)
    except Exception as exc:
        emit(error_response(str(exc), error_type="network_error"))
        sys.exit(1)

    emit(parsed)

    if parsed.get("status") != "success":
        sys.exit(1)


execute_tool = add_common_options(execute_tool)
