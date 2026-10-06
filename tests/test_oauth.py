"""Tests for OAuth login, logout, config, and client auth mode detection."""

from __future__ import annotations

import json

import pytest

from merge_cli.client import MergeClient, MergeClientError
from merge_cli.commands.login import MERGE_CLI_CLIENT_ID, _generate_pkce_pair
from merge_cli.common import get_client
from merge_cli.config import (
    OAuthConfig,
    clear_oauth_config,
    load_oauth_config,
    save_oauth_config,
)

BASE_URL = "https://test.merge.dev"
OAUTH_MCP_URL = f"{BASE_URL}/mcp"

MCP_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": True}},
        "serverInfo": {"name": "test", "version": "0.1.0"},
    },
}

MCP_LIST = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "tools": [
            {
                "name": "salesforce__list_contacts",
                "description": "List contacts",
                "inputSchema": {"type": "object"},
            },
        ]
    },
}


# ── PKCE ──────────────────────────────────────────────────────


class TestPKCE:
    def test_generate_pkce_pair_returns_two_strings(self):
        verifier, challenge = _generate_pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)
        assert len(verifier) > 40
        assert len(challenge) > 20

    def test_pkce_pairs_are_unique(self):
        pair1 = _generate_pkce_pair()
        pair2 = _generate_pkce_pair()
        assert pair1[0] != pair2[0]
        assert pair1[1] != pair2[1]

    def test_challenge_is_base64url(self):
        _, challenge = _generate_pkce_pair()
        # Base64url has no padding, no + or /
        assert "=" not in challenge
        assert "+" not in challenge
        assert "/" not in challenge


# ── OAuthConfig ───────────────────────────────────────────────


class TestOAuthConfig:
    def test_validate_all_present(self):
        cfg = OAuthConfig(
            access_token="tok_123",
            refresh_token="ref_123",
            client_id="merge-cli",
        )
        assert cfg.validate() == []

    def test_validate_missing_access_token(self):
        cfg = OAuthConfig(access_token="", refresh_token="ref", client_id="merge-cli")
        errors = cfg.validate()
        assert len(errors) == 1
        assert "access token" in errors[0]

    def test_validate_missing_client_id(self):
        cfg = OAuthConfig(access_token="tok", refresh_token="ref", client_id="")
        errors = cfg.validate()
        assert len(errors) == 1
        assert "client ID" in errors[0]

    def test_default_base_url(self):
        cfg = OAuthConfig(access_token="t", refresh_token="r", client_id="c")
        assert cfg.base_url == "https://ah-api.merge.dev"


# ── OAuth config persistence ─────────────────────────────────


class TestOAuthConfigPersistence:
    def test_save_and_load(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", config_file)
        monkeypatch.setattr("merge_cli.config.CONFIG_DIR", tmp_path)

        save_oauth_config(
            access_token="tok_abc",
            refresh_token="ref_abc",
            client_id="merge-cli",
            base_url="https://custom.example.com",
        )

        cfg = load_oauth_config()
        assert cfg is not None
        assert cfg.access_token == "tok_abc"
        assert cfg.refresh_token == "ref_abc"
        assert cfg.client_id == "merge-cli"
        assert cfg.base_url == "https://custom.example.com"

    def test_load_returns_none_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", tmp_path / "nonexistent.json")
        assert load_oauth_config() is None

    def test_load_returns_none_when_no_access_token(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"oauth": {"client_id": "merge-cli"}}))
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", config_file)
        assert load_oauth_config() is None

    def test_clear_preserves_client_id(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", config_file)
        monkeypatch.setattr("merge_cli.config.CONFIG_DIR", tmp_path)

        save_oauth_config(
            access_token="tok",
            refresh_token="ref",
            client_id="merge-cli",
            base_url="https://example.com",
        )

        clear_oauth_config()

        data = json.loads(config_file.read_text())
        assert data["oauth"]["client_id"] == "merge-cli"
        assert "access_token" not in data["oauth"]

        # load_oauth_config should return None (no access token)
        assert load_oauth_config() is None


# ── Client auth mode detection ────────────────────────────────


class TestClientAuthMode:
    def test_oauth_mode_uses_mcp_url(self):
        oauth_cfg = OAuthConfig(
            access_token="tok",
            refresh_token="ref",
            client_id="merge-cli",
            base_url=BASE_URL,
        )
        client = MergeClient(oauth_config=oauth_cfg)
        assert client._auth_mode == "oauth"
        assert client._mcp_url == "/mcp"
        client.close()

    def test_api_key_mode_uses_toolpack_url(self):
        from merge_cli.config import AgentHandlerConfig

        cfg = AgentHandlerConfig(
            api_key="pk_test",
            tool_pack_id="tp_1",
            registered_user_id="u_1",
            base_url=BASE_URL,
        )
        client = MergeClient(config=cfg)
        assert client._auth_mode == "api_key"
        assert "/tool-packs/tp_1/" in client._mcp_url
        client.close()

    def test_no_config_raises(self):
        with pytest.raises(ValueError, match="Either config or oauth_config"):
            MergeClient()


class TestOAuthClientMCP:
    def test_list_tools_via_oauth(self, httpx_mock):
        oauth_cfg = OAuthConfig(
            access_token="tok_test",
            refresh_token="ref_test",
            client_id="merge-cli",
            base_url=BASE_URL,
        )
        httpx_mock.add_response(
            url=OAUTH_MCP_URL,
            method="POST",
            json=MCP_INIT,
            headers={"Mcp-Session-Id": "s1"},
        )
        httpx_mock.add_response(
            url=OAUTH_MCP_URL,
            method="POST",
            json=MCP_LIST,
            headers={"Mcp-Session-Id": "s1"},
        )

        with MergeClient(oauth_config=oauth_cfg) as client:
            tools = client.list_tools()

        assert len(tools) == 1
        assert tools[0]["name"] == "salesforce__list_contacts"

    def test_401_triggers_refresh(self, httpx_mock, tmp_path, monkeypatch):
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", tmp_path / "config.json")
        monkeypatch.setattr("merge_cli.config.CONFIG_DIR", tmp_path)

        oauth_cfg = OAuthConfig(
            access_token="old_tok",
            refresh_token="ref_tok",
            client_id="merge-cli",
            base_url=BASE_URL,
        )

        # First request: 401
        httpx_mock.add_response(
            url=OAUTH_MCP_URL,
            method="POST",
            status_code=401,
        )
        # Refresh token request: success
        httpx_mock.add_response(
            url=f"{BASE_URL}/o/token/",
            method="POST",
            json={"access_token": "new_tok", "refresh_token": "new_ref"},
        )
        # Re-init after refresh
        httpx_mock.add_response(
            url=OAUTH_MCP_URL,
            method="POST",
            json=MCP_INIT,
            headers={"Mcp-Session-Id": "s2"},
        )
        # Retry the original request
        httpx_mock.add_response(
            url=OAUTH_MCP_URL,
            method="POST",
            json=MCP_LIST,
            headers={"Mcp-Session-Id": "s2"},
        )

        with MergeClient(oauth_config=oauth_cfg) as client:
            client._session_id = "s1"
            data = client._mcp_request("tools/list")

        assert data["result"]["tools"][0]["name"] == "salesforce__list_contacts"

    def test_401_without_refresh_token_raises(self, httpx_mock):
        oauth_cfg = OAuthConfig(
            access_token="tok",
            refresh_token="",
            client_id="merge-cli",
            base_url=BASE_URL,
        )
        httpx_mock.add_response(
            url=OAUTH_MCP_URL,
            method="POST",
            status_code=401,
        )

        with MergeClient(oauth_config=oauth_cfg) as client:
            client._session_id = "s1"
            with pytest.raises(MergeClientError, match="merge login"):
                client._mcp_request("tools/list")


# ── get_client auto-detection ─────────────────────────────────


class TestGetClient:
    def test_prefers_oauth_over_api_key(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "agent_handler": {
                        "api_key": "pk_test",
                        "tool_pack_id": "tp_1",
                        "registered_user_id": "u_1",
                    },
                    "oauth": {
                        "access_token": "tok_test",
                        "refresh_token": "ref_test",
                        "client_id": "merge-cli",
                    },
                }
            )
        )
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", config_file)

        client, errors = get_client()
        assert errors == []
        assert client is not None
        assert client._auth_mode == "oauth"
        client.close()

    def test_falls_back_to_api_key(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "agent_handler": {
                        "api_key": "pk_test",
                        "tool_pack_id": "tp_1",
                        "registered_user_id": "u_1",
                    },
                }
            )
        )
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", config_file)

        client, errors = get_client()
        assert errors == []
        assert client is not None
        assert client._auth_mode == "api_key"
        client.close()

    def test_returns_errors_when_no_auth(self, tmp_path, monkeypatch):
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", tmp_path / "nonexistent.json")

        client, errors = get_client()
        assert client is None
        assert len(errors) == 1
        assert "merge login" in errors[0]


# ── Constants ─────────────────────────────────────────────────


class TestConstants:
    def test_merge_cli_client_id(self):
        assert MERGE_CLI_CLIENT_ID == "merge-cli"
