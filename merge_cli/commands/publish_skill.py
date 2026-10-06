"""merge publish-skill — publish a SKILL.md or a skill directory to your library."""

from __future__ import annotations

import base64
import io
import sys
import zipfile
from pathlib import Path

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response, warn

SKILL_MD_FILENAME = "SKILL.md"
SKIPPED_NAMES = {"__pycache__", ".git", ".DS_Store", ".venv", "node_modules"}


def _is_skipped(relpath: Path) -> bool:
    """Editor and VCS droppings, which would eat into the server's file cap."""
    return any(part in SKIPPED_NAMES or part.startswith(".") for part in relpath.parts)


def build_bundle(skill_dir: Path) -> bytes:
    """Zip a skill directory, SKILL.md at the archive root.

    Raises ValueError when the directory has no SKILL.md, so the caller fails
    locally rather than spending a round-trip to be told the same thing.

    Symlinks are skipped rather than followed. Following one would read through
    to its target, so a link named like an ordinary file could pull anything the
    user can read into a bundle headed for the shared skill store — and the
    skip-list only ever sees the link's own name. The server refuses symlink
    entries for the same reason; resolving them here would hand it content it
    could no longer recognise as one.
    """
    if not (skill_dir / SKILL_MD_FILENAME).is_file():
        msg = f"{skill_dir} has no {SKILL_MD_FILENAME} at its root."
        raise ValueError(msg)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(skill_dir.rglob("*")):
            relpath = path.relative_to(skill_dir)
            if path.is_symlink():
                warn(f"Skipped symlink: {relpath}")
                continue
            if not path.is_file():
                continue
            if _is_skipped(relpath):
                continue
            archive.write(path, arcname=str(relpath))
    return buffer.getvalue()


@click.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--slug", default=None, help="Publish a new version of this skill slug.")
@click.option("--name", default=None, help="Override the frontmatter name.")
@click.option("--description", default=None, help="Override the frontmatter description.")
@click.option("--release-notes", default=None, help="What changed, for this version.")
@click.option(
    "--action",
    type=click.Choice(["draft", "submit", "publish"]),
    default="publish",
    show_default=True,
    help=(
        "publish makes the skill usable now; draft stores it without making it "
        "usable; submit sends it to an administrator to review and share with "
        "the organization. Submitting a brand-new skill needs --scope org, "
        "since a personal skill is never reviewed."
    ),
)
@click.option(
    "--scope",
    type=click.Choice(["personal", "org"]),
    default=None,
    help=(
        "Who the skill reaches, defaulting to personal (only you). Use "
        "--scope org with --action submit to propose it for the whole "
        "organization; publishing straight to org needs administrator "
        "permission. Sets the reach only when the skill is first created: on a "
        "new version of an existing skill, omit it — a value that contradicts "
        "the skill's current reach is rejected rather than ignored."
    ),
)
def publish_skill(
    path: Path,
    slug: str | None,
    name: str | None,
    description: str | None,
    release_notes: str | None,
    action: str,
    scope: str | None,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """Publish PATH (a SKILL.md file, or a directory holding one) to your skills.

    Publishing again with the same slug adds a new version. Without --slug the
    slug comes from the frontmatter name, so renaming creates a separate skill.

    Use --action to stage a draft or submit the skill for review, and --scope to
    ask for organization-wide reach instead of your personal library. A new
    skill submitted for review needs --scope org: a personal skill is never
    reviewed, so --action submit on its own is refused.
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

    arguments: dict[str, str] = {}
    try:
        if path.is_dir():
            arguments["bundle_base64"] = base64.b64encode(build_bundle(path)).decode()
        else:
            arguments["skill_md"] = path.read_text(encoding="utf-8")
    except ValueError as exc:
        emit(error_response(str(exc), error_type="invalid_input"))
        sys.exit(1)
    except OSError as exc:
        emit(error_response(str(exc), error_type="invalid_input"))
        sys.exit(1)

    arguments["action"] = action

    for key, value in (
        ("slug", slug),
        ("name", name),
        ("description", description),
        ("release_notes", release_notes),
        ("access_scope", scope),
    ):
        if value is not None:
            arguments[key] = value

    try:
        with client:
            raw_result = client.call_tool("publish_skill", arguments)
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


publish_skill = add_common_options(publish_skill)
