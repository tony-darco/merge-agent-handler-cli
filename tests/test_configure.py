"""Tests for merge configure command."""

from __future__ import annotations

import json

from click.testing import CliRunner

from merge_cli.commands.configure import configure


def test_configure_saves_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    saved = {}

    def mock_save(cfg):
        saved.update(cfg)
        config_file.write_text(json.dumps(cfg))

    monkeypatch.setattr("merge_cli.config._load_config_file", lambda: {})
    monkeypatch.setattr("merge_cli.config._save_config_file", mock_save)

    runner = CliRunner()
    result = runner.invoke(
        configure,
        input="pk_test_key\ntp_123\nuser_456\nhttps://ah-api.merge.dev\n",
    )

    assert result.exit_code == 0
    assert "Configuration saved" in result.output
    assert saved["agent_handler"]["api_key"] == "pk_test_key"
    assert saved["agent_handler"]["tool_pack_id"] == "tp_123"
    assert saved["agent_handler"]["registered_user_id"] == "user_456"


def test_configure_shows_existing_defaults(monkeypatch):
    existing = {
        "agent_handler": {
            "api_key": "existing_key",
            "tool_pack_id": "existing_tp",
            "registered_user_id": "existing_user",
            "base_url": "https://custom.example.com",
        }
    }
    monkeypatch.setattr("merge_cli.config._load_config_file", lambda: existing)
    monkeypatch.setattr("merge_cli.config._save_config_file", lambda cfg: None)

    runner = CliRunner()
    # Just press enter for all prompts to accept defaults
    result = runner.invoke(configure, input="\n\n\n\n")

    assert result.exit_code == 0
