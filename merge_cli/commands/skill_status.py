"""merge unpublish-skill / republish-skill — retire a skill or bring it back.

Two verb commands over one server tool (``update_skill``). The MCP surface keeps
it to a single tool because every tool costs context in an agent's tool list;
a CLI has no such budget, so the names match the verbs a caller already knows
from list-skills / retrieve-skill / publish-skill.
"""

from __future__ import annotations

import sys

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response


def _set_skill_active(
    slug: str,
    *,
    is_active: bool,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
) -> None:
    """Call ``update_skill`` and emit its envelope, exiting non-zero on failure.

    Shared by both commands so the two differ only in the flag they send and the
    words in their help.
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

    try:
        with client:
            raw_result = client.call_tool("update_skill", {"skill": slug, "is_active": is_active})
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


@click.command()
@click.argument("slug")
def unpublish_skill(
    slug: str,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """Unpublish SLUG so it stops appearing in list-skills and can't be retrieved.

    Nothing is deleted — versions, content and sharing all stay — so
    `merge republish-skill SLUG` brings it back at the same version with no
    re-upload. A skill that was never published has nothing to retire.
    """
    _set_skill_active(
        slug,
        is_active=False,
        api_key=api_key,
        tool_pack_id=tool_pack_id,
        registered_user_id=registered_user_id,
        base_url=base_url,
    )


@click.command()
@click.argument("slug")
def republish_skill(
    slug: str,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """Republish SLUG, restoring it at its last published version.

    Nothing is re-uploaded. A skill that was never published goes live through
    `merge publish-skill` instead.
    """
    _set_skill_active(
        slug,
        is_active=True,
        api_key=api_key,
        tool_pack_id=tool_pack_id,
        registered_user_id=registered_user_id,
        base_url=base_url,
    )


unpublish_skill = add_common_options(unpublish_skill)
republish_skill = add_common_options(republish_skill)
