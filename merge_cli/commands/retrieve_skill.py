"""merge retrieve-skill — fetch a skill's SKILL.md (or one bundled file)."""

from __future__ import annotations

import sys

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response


@click.command()
@click.argument("skill")
@click.option(
    "--path",
    default=None,
    help="Fetch one bundled file by its path instead of the SKILL.md body.",
)
def retrieve_skill(
    skill: str,
    path: str | None,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """Retrieve SKILL (by slug): its SKILL.md body + manifest, or one file via --path."""
    client, errors = get_client(
        api_key=api_key,
        tool_pack_id=tool_pack_id,
        registered_user_id=registered_user_id,
        base_url=base_url,
    )
    if errors or client is None:
        emit(config_error(errors))
        sys.exit(1)

    arguments: dict[str, str] = {"skill": skill}
    # `is not None` (not truthiness): forward an explicit --path "" so the server
    # rejects it, rather than silently returning the SKILL.md body.
    if path is not None:
        arguments["path"] = path

    try:
        with client:
            raw_result = client.call_tool("retrieve_skill", arguments)
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


retrieve_skill = add_common_options(retrieve_skill)
