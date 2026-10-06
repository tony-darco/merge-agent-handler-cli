"""merge list-skills — list the skills available to the authenticated user."""

from __future__ import annotations

import sys

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response


@click.command()
@click.option("--keyword", default=None, help="Filter skills by name/description.")
@click.option(
    "--status",
    type=click.Choice(["published", "draft", "in_review", "rejected"]),
    multiple=True,
    help=(
        "Repeatable. Defaults to the skills you can retrieve. Add draft, "
        "in_review or rejected to also list your own work in those states, "
        "which nobody else can see; a rejected one carries the reviewer's reason."
    ),
)
def list_skills(
    keyword: str | None,
    status: tuple[str, ...],
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """List skills, by default the ones you can retrieve.

    --keyword filters by name and description. --status widens the list to your
    own draft, in-review or rejected work, which nobody else can see and which
    retrieve-skill cannot read. Each row carries its status, and unpublished
    rows carry version_number and rejection_reason.
    """
    client, errors = get_client(
        api_key=api_key,
        tool_pack_id=tool_pack_id,
        registered_user_id=registered_user_id,
        base_url=base_url,
    )
    if errors or client is None:
        emit(config_error(errors))
        sys.exit(1)

    # `is not None` (not truthiness): forward an explicitly provided --keyword ""
    # rather than silently dropping it and listing everything.
    arguments: dict[str, object] = {"keyword": keyword} if keyword is not None else {}
    if status:
        arguments["status"] = list(status)

    try:
        with client:
            raw_result = client.call_tool("list_skills", arguments)
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


list_skills = add_common_options(list_skills)
