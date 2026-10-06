"""merge search-tools — semantic search for tools by intent."""

from __future__ import annotations

import sys
from typing import Any

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response


def _compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Aggressively compact schema: strip descriptions, simplify nullable types."""
    if not isinstance(schema, dict):
        return schema

    # Simplify anyOf: [{type: X}, {type: null}] → {type: X, nullable: true}
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and len(any_of) == 2:
        non_null = [s for s in any_of if isinstance(s, dict) and s.get("type") != "null"]
        has_null = any(isinstance(s, dict) and s.get("type") == "null" for s in any_of)
        if has_null and len(non_null) == 1:
            simplified = _compact_schema(non_null[0])
            simplified["nullable"] = True
            return simplified

    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k in ("description", "title"):
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _compact_schema(pv) for pk, pv in v.items()}
        elif k in ("items", "anyOf", "oneOf", "allOf") and isinstance(v, (dict, list)):
            if isinstance(v, list):
                out[k] = [_compact_schema(item) if isinstance(item, dict) else item for item in v]
            else:
                out[k] = _compact_schema(v)
        else:
            out[k] = v
    return out


@click.command()
@click.argument("intent")
@click.option("--connector", multiple=True, help="Filter by connector slug (repeatable).")
@click.option("--max-results", default=2, type=int, help="Max results (1-50).")
@click.option(
    "--schema",
    type=click.Choice(["compact", "full", "none"], case_sensitive=False),
    default="compact",
    help="Schema detail level: compact (default), full (with descriptions), or none.",
)
def search_tools(
    intent: str,
    connector: tuple[str, ...],
    max_results: int,
    schema: str,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """Search for tools matching a natural language INTENT."""
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
            data = client.search_tools(
                intent,
                connector_slugs=list(connector) if connector else None,
                max_results=max_results,
            )

    except MergeClientError as exc:
        emit(error_response(str(exc), error_type="api_error"))
        sys.exit(1)
    except Exception as exc:
        emit(error_response(str(exc), error_type="network_error"))
        sys.exit(1)

    tools = data.get("tools", [])
    requestable_tools = data.get("requestable_tools", [])

    # Schema handling: compact by default, full with descriptions, none to omit
    for tool_list in (tools, requestable_tools):
        if schema == "none":
            for tool in tool_list:
                tool.pop("input_schema", None)
        elif schema == "compact":
            for tool in tool_list:
                if "input_schema" in tool:
                    tool["input_schema"] = _compact_schema(tool["input_schema"])

    output: dict[str, Any] = {
        "tools": tools,
        "total_results": data.get("total_results", len(tools)),
        "hint": "To execute: merge execute-tool <tool_name> '<json_params>'",
    }
    if requestable_tools:
        output["requestable_tools"] = requestable_tools
    if data.get("message"):
        output["message"] = data["message"]
    if data.get("request_access_tool_name"):
        output["request_access_tool_name"] = data["request_access_tool_name"]

    emit(output)


search_tools = add_common_options(search_tools)
