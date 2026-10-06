"""Tests for merge authenticate."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from merge_cli.client import MergeClient, MergeClientError
from merge_cli.commands.authenticate import authenticate
from merge_cli.config import AgentHandlerConfig


@pytest.fixture
def runner():
    return CliRunner()


def _client_with_result(raw_result: dict) -> MagicMock:
    """A MergeClient whose call_tool returns `raw_result`; parse_tool_result is real."""
    client = MagicMock(spec=MergeClient)
    client.__enter__.return_value = client
    client.call_tool.return_value = raw_result
    real = MergeClient(AgentHandlerConfig(api_key="k", tool_pack_id="t", registered_user_id="u"))
    client.parse_tool_result.side_effect = real.parse_tool_result
    return client


def _mcp_text(payload: dict, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": is_error}


def test_authenticate_prints_magic_link(runner):
    client = _client_with_result(
        _mcp_text({"status": "pending", "magic_link_url": "https://link.merge.dev/abc"})
    )
    with patch("merge_cli.commands.authenticate.get_client", return_value=(client, [])):
        result = runner.invoke(authenticate, ["slack"])

    assert result.exit_code == 0, result.output
    client.call_tool.assert_called_once_with("authenticate_slack", {})
    output = json.loads(result.output)
    assert output["result"] == {
        "connector": "slack",
        "magic_link_url": "https://link.merge.dev/abc",
    }
    assert "Show this URL to your user" in output["hint"]


def test_authenticate_falls_back_to_raw_result(runner):
    client = _client_with_result(_mcp_text({"message": "Already connected."}))
    with patch("merge_cli.commands.authenticate.get_client", return_value=(client, [])):
        result = runner.invoke(authenticate, ["slack"])

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["result"] == {"message": "Already connected."}


def test_authenticate_tool_error(runner):
    client = _client_with_result(
        _mcp_text({"error": "not_found", "message": "Unknown connector"}, is_error=True)
    )
    with patch("merge_cli.commands.authenticate.get_client", return_value=(client, [])):
        result = runner.invoke(authenticate, ["nope"])

    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "not_found"


def test_authenticate_api_error(runner):
    client = _client_with_result({})
    client.call_tool.side_effect = MergeClientError("MCP request failed: 500")
    with patch("merge_cli.commands.authenticate.get_client", return_value=(client, [])):
        result = runner.invoke(authenticate, ["slack"])

    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "api_error"


@pytest.mark.parametrize("slug", ["Slack", "slack;rm", "../etc", "a" * 65, ""])
def test_authenticate_rejects_invalid_slug(runner, slug):
    with patch("merge_cli.commands.authenticate.get_client") as get_client:
        result = runner.invoke(authenticate, [slug] if slug else ["--", slug])

    assert result.exit_code == 1
    get_client.assert_not_called()
    assert json.loads(result.output)["error_type"] == "invalid_params"


def test_authenticate_missing_config(runner):
    with patch(
        "merge_cli.commands.authenticate.get_client", return_value=(None, ["Not authenticated."])
    ):
        result = runner.invoke(authenticate, ["slack"])

    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "config_error"
