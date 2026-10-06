"""Tests for config loading with priority: CLI flags > env vars > config file."""

from __future__ import annotations

import json

import pytest

from merge_cli.config import AgentHandlerConfig, load_ah_config, validate_base_url


class TestAgentHandlerConfig:
    def test_validate_all_present(self):
        cfg = AgentHandlerConfig(api_key="pk_123", tool_pack_id="tp_1", registered_user_id="u_1")
        assert cfg.validate() == []

    def test_validate_missing_api_key(self):
        cfg = AgentHandlerConfig(api_key="", tool_pack_id="tp_1", registered_user_id="u_1")
        errors = cfg.validate()
        assert len(errors) == 1
        assert "API key" in errors[0]

    def test_validate_all_missing(self):
        cfg = AgentHandlerConfig(api_key="", tool_pack_id="", registered_user_id="")
        assert len(cfg.validate()) == 3

    def test_default_base_url(self):
        cfg = AgentHandlerConfig(api_key="k", tool_pack_id="t", registered_user_id="u")
        assert cfg.base_url == "https://ah-api.merge.dev"


class TestLoadAhConfig:
    def test_cli_flags_override_everything(self, tmp_path, monkeypatch):
        # Set env vars
        monkeypatch.setenv("MERGE_AH_API_KEY", "env_key")
        monkeypatch.setenv("MERGE_AH_TOOL_PACK_ID", "env_tp")
        monkeypatch.setenv("MERGE_AH_REGISTERED_USER_ID", "env_user")

        # Write config file
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "agent_handler": {
                        "api_key": "file_key",
                        "tool_pack_id": "file_tp",
                        "registered_user_id": "file_user",
                    }
                }
            )
        )
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", config_file)

        cfg = load_ah_config(
            api_key="cli_key", tool_pack_id="cli_tp", registered_user_id="cli_user"
        )
        assert cfg.api_key == "cli_key"
        assert cfg.tool_pack_id == "cli_tp"
        assert cfg.registered_user_id == "cli_user"

    def test_env_vars_override_config_file(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "agent_handler": {
                        "api_key": "file_key",
                        "tool_pack_id": "file_tp",
                        "registered_user_id": "file_user",
                    }
                }
            )
        )
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", config_file)
        monkeypatch.setenv("MERGE_AH_API_KEY", "env_key")
        # Don't set other env vars — they should fall through to config file
        monkeypatch.delenv("MERGE_AH_TOOL_PACK_ID", raising=False)
        monkeypatch.delenv("MERGE_AH_REGISTERED_USER_ID", raising=False)

        cfg = load_ah_config()
        assert cfg.api_key == "env_key"
        assert cfg.tool_pack_id == "file_tp"
        assert cfg.registered_user_id == "file_user"

    def test_config_file_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MERGE_AH_API_KEY", raising=False)
        monkeypatch.delenv("MERGE_AH_TOOL_PACK_ID", raising=False)
        monkeypatch.delenv("MERGE_AH_REGISTERED_USER_ID", raising=False)

        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "agent_handler": {
                        "api_key": "file_key",
                        "tool_pack_id": "file_tp",
                        "registered_user_id": "file_user",
                        "base_url": "https://custom.example.com",
                    }
                }
            )
        )
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", config_file)

        cfg = load_ah_config()
        assert cfg.api_key == "file_key"
        assert cfg.tool_pack_id == "file_tp"
        assert cfg.registered_user_id == "file_user"
        assert cfg.base_url == "https://custom.example.com"

    def test_missing_config_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MERGE_AH_API_KEY", raising=False)
        monkeypatch.delenv("MERGE_AH_TOOL_PACK_ID", raising=False)
        monkeypatch.delenv("MERGE_AH_REGISTERED_USER_ID", raising=False)
        monkeypatch.setattr("merge_cli.config.CONFIG_FILE", tmp_path / "nonexistent.json")

        cfg = load_ah_config()
        assert cfg.api_key == ""
        assert cfg.tool_pack_id == ""
        assert cfg.registered_user_id == ""
        assert cfg.base_url == "https://ah-api.merge.dev"


class TestValidateBaseUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://ah-api.merge.dev",
            "https://ah-api-develop.merge.dev",
            "https://merge.dev",
        ],
    )
    def test_allows_merge_dev_over_https(self, url):
        assert validate_base_url(url) is None

    @pytest.mark.parametrize(
        "url",
        [
            "http://ah-api.merge.dev",  # https required
            "https://evilmerge.dev",
            "https://merge.dev.attacker.com",
            "https://example.com",
            "ftp://ah-api.merge.dev",
        ],
    )
    def test_rejects_other_hosts(self, url, monkeypatch):
        monkeypatch.setenv("MERGE_AH_ALLOW_LOCALHOST_BASE_URL", "1")
        assert validate_base_url(url) is not None

    @pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000"])
    def test_localhost_needs_env_flag(self, url, monkeypatch):
        monkeypatch.delenv("MERGE_AH_ALLOW_LOCALHOST_BASE_URL", raising=False)
        error = validate_base_url(url)
        assert error is not None
        assert "MERGE_AH_ALLOW_LOCALHOST_BASE_URL" in error

        monkeypatch.setenv("MERGE_AH_ALLOW_LOCALHOST_BASE_URL", "1")
        assert validate_base_url(url) is None
