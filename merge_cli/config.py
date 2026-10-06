"""Configuration loading with priority: CLI flags > env vars > .env file > config file."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

CONFIG_DIR = Path.home() / ".merge"
CONFIG_FILE = CONFIG_DIR / "config.json"
VERSION_CACHE_FILE = CONFIG_DIR / "version_cache.json"

DEFAULT_BASE_URL = "https://ah-api.merge.dev"

ALLOW_LOCALHOST_ENV = "MERGE_AH_ALLOW_LOCALHOST_BASE_URL"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def validate_base_url(base_url: str) -> str | None:
    """Return an error message unless base_url is an allowed host, else None.

    Every request sends the credential to base_url's host, so only https://*.merge.dev
    is accepted — plus localhost when MERGE_AH_ALLOW_LOCALHOST_BASE_URL is set (dev only).
    """
    try:
        parts = urlsplit(base_url)
    except ValueError:
        return f"Base URL is not a valid URL: {base_url}"
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and (host == "merge.dev" or host.endswith(".merge.dev")):
        return None
    if parts.scheme in ("http", "https") and host in _LOCAL_HOSTS:
        if os.environ.get(ALLOW_LOCALHOST_ENV):
            return None
        return (
            f"Base URL {base_url} points at localhost."
            f" Set {ALLOW_LOCALHOST_ENV}=1 to allow it for local development."
        )
    return (
        f"Base URL {base_url} is not allowed. Only https://*.merge.dev is accepted"
        f" (or localhost with {ALLOW_LOCALHOST_ENV}=1)."
    )


@dataclass
class AgentHandlerConfig:
    api_key: str
    tool_pack_id: str
    registered_user_id: str
    base_url: str = DEFAULT_BASE_URL
    # Written by `merge agent signup`; empty when the key came from env vars or `merge configure`.
    organization_id: str = ""
    claim_url: str = ""
    claim_expires_at: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.api_key:
            errors.append("API key is required. Set MERGE_AH_API_KEY or run `merge agent signup`.")
        if not self.tool_pack_id:
            errors.append(
                "Tool pack ID is required. Set MERGE_AH_TOOL_PACK_ID or run `merge agent signup`."
            )
        if not self.registered_user_id:
            errors.append(
                "Registered user ID is required."
                " Set MERGE_AH_REGISTERED_USER_ID or run `merge agent signup`."
            )
        return errors


@dataclass
class OAuthConfig:
    access_token: str
    refresh_token: str
    client_id: str
    base_url: str = DEFAULT_BASE_URL

    def validate(self) -> list[str]:
        errors = []
        if not self.access_token:
            errors.append("OAuth access token is missing. Run `merge login`.")
        if not self.client_id:
            errors.append("OAuth client ID is missing. Run `merge login`.")
        return errors


def _load_config_file() -> dict:
    """Load config from ~/.merge/config.json if it exists."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_config_file(config: dict) -> None:
    """Write config to ~/.merge/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")
    CONFIG_FILE.chmod(0o600)


def load_ah_config(
    *,
    api_key: str | None = None,
    tool_pack_id: str | None = None,
    registered_user_id: str | None = None,
    base_url: str | None = None,
) -> AgentHandlerConfig:
    """Load Agent Handler config with priority: CLI flags > env vars > config file."""
    file_cfg = _load_config_file().get("agent_handler", {})

    return AgentHandlerConfig(
        api_key=api_key or os.environ.get("MERGE_AH_API_KEY") or file_cfg.get("api_key", ""),
        tool_pack_id=(
            tool_pack_id
            or os.environ.get("MERGE_AH_TOOL_PACK_ID")
            or file_cfg.get("tool_pack_id", "")
        ),
        registered_user_id=(
            registered_user_id
            or os.environ.get("MERGE_AH_REGISTERED_USER_ID")
            or file_cfg.get("registered_user_id", "")
        ),
        base_url=(
            base_url
            or os.environ.get("MERGE_AH_BASE_URL")
            or file_cfg.get("base_url")
            or DEFAULT_BASE_URL
        ),
        organization_id=file_cfg.get("organization_id", ""),
        claim_url=file_cfg.get("claim_url", ""),
        claim_expires_at=file_cfg.get("claim_expires_at", ""),
    )


def save_ah_config(cfg: AgentHandlerConfig) -> None:
    """Merge `cfg`'s non-empty fields into the `agent_handler` block of the config file.

    Merging (not replacing) keeps signup-only fields like claim_url when a caller
    such as `merge configure` saves a config built without them.
    """
    config = _load_config_file()
    existing = config.get("agent_handler", {})
    config["agent_handler"] = {**existing, **{k: v for k, v in asdict(cfg).items() if v}}
    _save_config_file(config)


def load_oauth_config(
    *,
    base_url: str | None = None,
) -> OAuthConfig | None:
    """Load OAuth config from config file. Returns None if not configured."""
    file_cfg = _load_config_file().get("oauth", {})

    access_token = file_cfg.get("access_token", "")
    if not access_token:
        return None

    return OAuthConfig(
        access_token=access_token,
        refresh_token=file_cfg.get("refresh_token", ""),
        client_id=file_cfg.get("client_id", ""),
        base_url=(
            base_url
            or os.environ.get("MERGE_AH_BASE_URL")
            or file_cfg.get("base_url")
            or DEFAULT_BASE_URL
        ),
    )


def save_oauth_config(
    access_token: str,
    refresh_token: str,
    client_id: str,
    base_url: str = DEFAULT_BASE_URL,
) -> None:
    """Save OAuth tokens to config file."""
    config = _load_config_file()
    config["oauth"] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "base_url": base_url,
    }
    _save_config_file(config)


def clear_oauth_config() -> None:
    """Remove OAuth tokens from config file, preserving client_id for re-login."""
    config = _load_config_file()
    oauth = config.get("oauth", {})
    client_id = oauth.get("client_id")
    base_url = oauth.get("base_url")

    if client_id:
        config["oauth"] = {"client_id": client_id, "base_url": base_url}
    else:
        config.pop("oauth", None)

    _save_config_file(config)
