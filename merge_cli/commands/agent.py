"""merge agent — agent-only signup and identity commands."""

from __future__ import annotations

import sys
from pathlib import Path

import click
import httpx

from merge_cli.commands.setup import SETUP_TARGETS, detect_host, run_setup
from merge_cli.config import (
    DEFAULT_BASE_URL,
    AgentHandlerConfig,
    load_ah_config,
    save_ah_config,
    validate_base_url,
)
from merge_cli.output import emit, error_response

SIGNUP_TIMEOUT = 30.0

# Fixed local hint — never echo server-controlled text (e.g. next_step) to the agent.
SIGNUP_HINT = (
    "Credentials saved to ~/.merge/config.json — never print the API key."
    " Give claim_url to your user so they can claim the organization."
    ' Next: run `merge search-tools "<intent>"` to find tools.'
)


def _server_snippet(text: str, limit: int = 200) -> str:
    """Collapse whitespace and truncate a server error body for safe display."""
    snippet = " ".join(text.split())
    return snippet[:limit] + ("…" if len(snippet) > limit else "")


@click.group()
def agent():
    """Commands for AI agents acting without a human at the keyboard."""


@agent.command()
@click.option(
    "--setup",
    "setup_target",
    type=click.Choice(SETUP_TARGETS, case_sensitive=False),
    default=None,
    help="Instruction-file target to write (default: detected from the environment).",
)
@click.option("--no-setup", is_flag=True, help="Skip writing agent instruction files.")
@click.option("--base-url", envvar="MERGE_AH_BASE_URL", default=None, help="Base URL override.")
@click.option(
    "--project-dir",
    default=".",
    type=click.Path(exists=True, file_okay=False),
    help="Project directory for instruction files (default: current directory).",
)
def signup(setup_target: str | None, no_setup: bool, base_url: str | None, project_dir: str):
    """Create an organization, save credentials, and print the claim URL for your user.

    Refuses to run when credentials already exist — run `merge agent whoami` instead.
    """
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
    url_error = validate_base_url(base_url)
    if url_error:
        emit(error_response(url_error, error_type="config_error"))
        sys.exit(1)

    existing = load_ah_config(base_url=base_url)
    if existing.api_key:
        emit(
            error_response(
                "Already signed up.",
                error_type="already_signed_up",
                hint="Run `merge agent whoami` to see the existing account.",
            )
        )
        sys.exit(1)

    try:
        resp = httpx.post(f"{base_url}/api/v1/agent/signup/", json={}, timeout=SIGNUP_TIMEOUT)
    except httpx.HTTPError as exc:
        emit(error_response(f"Signup request failed: {exc}", error_type="network_error"))
        sys.exit(1)
    if resp.status_code not in (200, 201):
        emit(
            error_response(
                f"Signup failed with HTTP {resp.status_code}."
                f" Server said: {_server_snippet(resp.text)}",
                error_type="api_error",
            )
        )
        sys.exit(1)

    try:
        data = resp.json()
        api_key = data["api_key"]
        tool_pack_id = data["tool_pack_id"]
        registered_user_id = data["registered_user_id"]
    except (ValueError, KeyError):
        emit(
            error_response(
                "Signup succeeded but the response was malformed.",
                error_type="api_error",
            )
        )
        sys.exit(1)
    save_ah_config(
        AgentHandlerConfig(
            api_key=api_key,
            tool_pack_id=tool_pack_id,
            registered_user_id=registered_user_id,
            base_url=base_url,
            organization_id=data.get("organization", {}).get("id", ""),
            claim_url=data.get("claim_url", ""),
            claim_expires_at=data.get("claim_expires_at", ""),
        )
    )

    written_for = None
    if not no_setup:
        written_for = setup_target or detect_host()
        run_setup(written_for, Path(project_dir).resolve())

    emit(
        {
            "result": {
                "organization_id": data.get("organization", {}).get("id", ""),
                "organization_name": data.get("organization", {}).get("name", ""),
                "tool_pack_id": tool_pack_id,
                "registered_user_id": registered_user_id,
                "claim_url": data.get("claim_url", ""),
                "claim_expires_at": data.get("claim_expires_at", ""),
                "setup_target": written_for,
            },
            "status": "success",
            "hint": SIGNUP_HINT,
        }
    )


@agent.command()
@click.option("--show-claim-url", is_flag=True, help="Include the claim URL in the output.")
def whoami(show_claim_url: bool):
    """Print the saved account ids. No network call."""
    cfg = load_ah_config()
    if not cfg.api_key:
        emit(
            error_response(
                "Not signed up.",
                error_type="config_error",
                hint="Run `merge agent signup` to create an account.",
            )
        )
        sys.exit(1)

    result = {
        "organization_id": cfg.organization_id,
        "tool_pack_id": cfg.tool_pack_id,
        "registered_user_id": cfg.registered_user_id,
        "base_url": cfg.base_url,
    }
    hint = "Pass --show-claim-url when your user still needs the claim URL."
    if show_claim_url:
        result["claim_url"] = cfg.claim_url
        result["claim_expires_at"] = cfg.claim_expires_at
        hint = "Give claim_url to your user if they have not claimed the organization yet."
    emit({"result": result, "status": "success", "hint": hint})
