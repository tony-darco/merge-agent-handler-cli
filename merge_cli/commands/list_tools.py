"""merge list-tools — list all available tools."""

from __future__ import annotations

import sys
from typing import Any

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response


def _extract_required_params(schema: dict[str, Any]) -> list[str]:
    """Extract top-level required parameter names from a tool's input schema."""
    # Tools typically have {properties: {input: {properties: {...}, required: [...]}}}
    props = schema.get("properties", {})
    input_obj = props.get("input", {})
    if isinstance(input_obj, dict) and "properties" in input_obj:
        return input_obj.get("required", [])
    # Fallback: top-level required
    return schema.get("required", [])


@click.command()
@click.option("--connector", default=None, help="Filter by connector slug prefix.")
@click.option("--full", is_flag=True, default=False, help="Include full input schemas.")
@click.option(
    "--compact",
    is_flag=True,
    default=False,
    help="Show tool names with required param names only (minimal context).",
)
def list_tools(
    connector: str | None,
    full: bool,
    compact: bool,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """List all available tools (names and descriptions by default)."""
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
            tools = client.list_tools()
    except MergeClientError as exc:
        emit(error_response(str(exc), error_type="api_error"))
        sys.exit(1)
    except Exception as exc:
        emit(error_response(str(exc), error_type="network_error"))
        sys.exit(1)

    # Filter by connector prefix if specified
    if connector:
        tools = [
            t
            for t in tools
            if t.get("name", "").startswith(f"{connector}__")
            or t.get("name", "") == f"authenticate_{connector}"
        ]

    # Build output format
    if full:
        formatted = tools
    elif compact:
        formatted = []
        for t in tools:
            schema = t.get("inputSchema", t.get("input_schema", {}))
            params = _extract_required_params(schema)
            formatted.append({"name": t.get("name", ""), "params": params})
    else:
        formatted = [
            {"name": t.get("name", ""), "description": t.get("description", "")} for t in tools
        ]

    hint = "To execute: merge execute-tool <tool_name> '<json_params>'"
    if not compact:
        hint += ". Use 'merge search-tools <intent>' to get the input schema for a tool."

    emit(
        {
            "tools": formatted,
            "total": len(formatted),
            "hint": hint,
        }
    )


list_tools = add_common_options(list_tools)
