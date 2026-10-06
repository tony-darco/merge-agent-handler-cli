"""Tests for merge agent signup / whoami."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from merge_cli.commands.agent import agent

SIGNUP_RESPONSE = {
    "api_key": "pk_secret_key",
    "organization": {"id": "org_1", "name": "Agent Org"},
    "claim_url": "https://app.merge.dev/claim/abc",
    "claim_expires_at": "2026-09-04T00:00:00Z",
    "tool_pack_id": "tp_1",
    "registered_user_id": "ru_1",
    "next_step": 'Run: merge search-tools "<intent>". Guide: https://docs.merge.dev/x',
}


def _response(status_code: int, body: dict) -> MagicMock:
    resp = MagicMock(status_code=status_code, text=json.dumps(body))
    resp.json.return_value = body
    return resp


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def saved_config(monkeypatch):
    """Capture writes to the config file; start from an empty file."""
    store: dict = {}
    monkeypatch.setattr("merge_cli.config._load_config_file", lambda: dict(store))
    monkeypatch.setattr("merge_cli.config._save_config_file", lambda cfg: store.update(cfg))
    return store


@pytest.fixture
def no_setup_files(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "merge_cli.commands.agent.run_setup",
        lambda target, project: calls.append((target, str(project))),
    )
    return calls


def test_signup_saves_config_and_prints_claim_url(runner, saved_config, no_setup_files, tmp_path):
    with patch("merge_cli.commands.agent.httpx.post") as post:
        post.return_value = _response(201, SIGNUP_RESPONSE)
        result = runner.invoke(
            agent,
            ["signup", "--no-setup", "--base-url", "https://test.merge.dev/"],
        )

    assert result.exit_code == 0, result.output
    post.assert_called_once()
    assert post.call_args.args[0] == "https://test.merge.dev/api/v1/agent/signup/"

    ah = saved_config["agent_handler"]
    assert ah["api_key"] == "pk_secret_key"
    assert ah["tool_pack_id"] == "tp_1"
    assert ah["registered_user_id"] == "ru_1"
    assert ah["base_url"] == "https://test.merge.dev"
    assert ah["organization_id"] == "org_1"
    assert ah["claim_url"] == "https://app.merge.dev/claim/abc"
    assert ah["claim_expires_at"] == "2026-09-04T00:00:00Z"

    output = json.loads(result.output)
    assert output["status"] == "success"
    assert output["result"]["claim_url"] == "https://app.merge.dev/claim/abc"
    assert output["result"]["setup_target"] is None
    # The hint is fixed local text; server-controlled next_step must not be echoed.
    assert SIGNUP_RESPONSE["next_step"] not in output["hint"]
    assert "merge search-tools" in output["hint"]
    assert "pk_secret_key" not in result.output


def test_signup_runs_setup_for_detected_host(runner, saved_config, no_setup_files, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    with patch("merge_cli.commands.agent.httpx.post") as post:
        post.return_value = _response(201, SIGNUP_RESPONSE)
        result = runner.invoke(agent, ["signup"])

    assert result.exit_code == 0, result.output
    assert [t for t, _ in no_setup_files] == ["claude-code"]
    assert json.loads(result.output)["result"]["setup_target"] == "claude-code"


def test_signup_setup_flag_overrides_detection(runner, saved_config, no_setup_files, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    with patch("merge_cli.commands.agent.httpx.post") as post:
        post.return_value = _response(201, SIGNUP_RESPONSE)
        result = runner.invoke(agent, ["signup", "--setup", "cursor"])

    assert result.exit_code == 0, result.output
    assert [t for t, _ in no_setup_files] == ["cursor"]


def test_signup_refuses_when_already_configured(runner, saved_config, no_setup_files):
    saved_config["agent_handler"] = {
        "api_key": "pk_existing",
        "tool_pack_id": "tp",
        "registered_user_id": "ru",
    }
    with patch("merge_cli.commands.agent.httpx.post") as post:
        result = runner.invoke(agent, ["signup"])

    assert result.exit_code == 1
    post.assert_not_called()
    output = json.loads(result.output)
    assert output["error_type"] == "already_signed_up"
    assert "merge agent whoami" in output["hint"]


def test_signup_api_error(runner, saved_config, no_setup_files):
    with patch("merge_cli.commands.agent.httpx.post") as post:
        post.return_value = _response(429, {"detail": "slow down"})
        result = runner.invoke(agent, ["signup", "--no-setup"])

    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["error_type"] == "api_error"
    assert "Server said:" in output["message"]
    assert "agent_handler" not in saved_config


def test_signup_api_error_truncates_server_body(runner, saved_config, no_setup_files):
    resp = MagicMock(status_code=500, text="x" * 5000)
    with patch("merge_cli.commands.agent.httpx.post", return_value=resp):
        result = runner.invoke(agent, ["signup", "--no-setup"])

    assert result.exit_code == 1
    message = json.loads(result.output)["message"]
    assert "Server said:" in message
    assert len(message) < 300


def test_signup_rejects_non_merge_base_url(runner, saved_config, no_setup_files):
    with patch("merge_cli.commands.agent.httpx.post") as post:
        result = runner.invoke(agent, ["signup", "--base-url", "https://evil.example.com"])

    assert result.exit_code == 1
    post.assert_not_called()
    output = json.loads(result.output)
    assert output["error_type"] == "config_error"
    assert "merge.dev" in output["message"]


def test_signup_rejects_localhost_without_flag(runner, saved_config, no_setup_files, monkeypatch):
    monkeypatch.delenv("MERGE_AH_ALLOW_LOCALHOST_BASE_URL", raising=False)
    with patch("merge_cli.commands.agent.httpx.post") as post:
        result = runner.invoke(agent, ["signup", "--base-url", "http://localhost:8000"])

    assert result.exit_code == 1
    post.assert_not_called()
    assert "MERGE_AH_ALLOW_LOCALHOST_BASE_URL" in json.loads(result.output)["message"]


def test_signup_allows_localhost_with_flag(runner, saved_config, no_setup_files, monkeypatch):
    monkeypatch.setenv("MERGE_AH_ALLOW_LOCALHOST_BASE_URL", "1")
    with patch("merge_cli.commands.agent.httpx.post") as post:
        post.return_value = _response(201, SIGNUP_RESPONSE)
        result = runner.invoke(
            agent, ["signup", "--no-setup", "--base-url", "http://localhost:8000"]
        )

    assert result.exit_code == 0, result.output
    assert post.call_args.args[0] == "http://localhost:8000/api/v1/agent/signup/"


def test_signup_network_error(runner, saved_config, no_setup_files):
    with patch("merge_cli.commands.agent.httpx.post", side_effect=httpx.ConnectError("boom")):
        result = runner.invoke(agent, ["signup", "--no-setup"])

    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "network_error"


def test_whoami_prints_config_without_key(runner, saved_config):
    saved_config["agent_handler"] = {
        "api_key": "pk_secret_key",
        "tool_pack_id": "tp_1",
        "registered_user_id": "ru_1",
        "base_url": "https://test.merge.dev",
        "organization_id": "org_1",
        "claim_url": "https://app.merge.dev/claim/abc",
        "claim_expires_at": "2026-09-04T00:00:00Z",
    }
    with patch("merge_cli.commands.agent.httpx.post") as post:
        result = runner.invoke(agent, ["whoami"])

    assert result.exit_code == 0, result.output
    post.assert_not_called()
    output = json.loads(result.output)
    assert output["result"] == {
        "organization_id": "org_1",
        "tool_pack_id": "tp_1",
        "registered_user_id": "ru_1",
        "base_url": "https://test.merge.dev",
    }
    assert "claim/abc" not in result.output
    assert "pk_secret_key" not in result.output


def test_whoami_show_claim_url_flag(runner, saved_config):
    saved_config["agent_handler"] = {
        "api_key": "pk_secret_key",
        "tool_pack_id": "tp_1",
        "registered_user_id": "ru_1",
        "claim_url": "https://app.merge.dev/claim/abc",
        "claim_expires_at": "2026-09-04T00:00:00Z",
    }
    result = runner.invoke(agent, ["whoami", "--show-claim-url"])

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["result"]["claim_url"] == "https://app.merge.dev/claim/abc"
    assert output["result"]["claim_expires_at"] == "2026-09-04T00:00:00Z"
    assert "pk_secret_key" not in result.output


def test_whoami_not_signed_up(runner, saved_config):
    result = runner.invoke(agent, ["whoami"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "config_error"
