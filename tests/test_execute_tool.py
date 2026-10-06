"""Tests for merge execute-tool command."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from merge_cli.commands.execute_tool import execute_tool


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def env_vars(monkeypatch):
    monkeypatch.setenv("MERGE_AH_API_KEY", "pk_test_key")
    monkeypatch.setenv("MERGE_AH_TOOL_PACK_ID", "tp_123")
    monkeypatch.setenv("MERGE_AH_REGISTERED_USER_ID", "user_456")
    monkeypatch.setenv("MERGE_AH_BASE_URL", "https://test.merge.dev")


MCP_INIT_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": True}},
        "serverInfo": {"name": "ToolPack MCP Server", "version": "0.1.0"},
    },
}

MCP_CALL_SUCCESS = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [{"type": "text", "text": '{"ok": true, "ts": "123456.789"}'}],
        "isError": False,
    },
}

MCP_CALL_REAUTH = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": '{"error": "reauth_required", "message": "OAuth token expired."}',
            }
        ],
        "isError": True,
    },
}

MCP_CALL_BILLING = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": (
                    '{"error": "billing_limit_reached",'
                    ' "message": "Limit reached.",'
                    ' "billing_page_url": "https://billing.example.com"}'
                ),
            }
        ],
        "isError": True,
    },
}


def _setup_mcp_mocks(httpx_mock, base_url, tool_pack_id, user_id, call_response):
    """Set up init + call mocks for MCP endpoint."""
    url = f"{base_url}/api/v1/tool-packs/{tool_pack_id}/registered-users/{user_id}/mcp"
    # First call is initialize
    httpx_mock.add_response(
        url=url,
        method="POST",
        json=MCP_INIT_RESPONSE,
        headers={"Mcp-Session-Id": "session-abc"},
    )
    # Second call is tools/call
    httpx_mock.add_response(
        url=url,
        method="POST",
        json=call_response,
        headers={"Mcp-Session-Id": "session-abc"},
    )


def test_execute_tool_success(runner, env_vars, httpx_mock):
    _setup_mcp_mocks(httpx_mock, "https://test.merge.dev", "tp_123", "user_456", MCP_CALL_SUCCESS)

    result = runner.invoke(
        execute_tool,
        ["slack__post_message", '{"input": {"channel": "#general", "text": "hi"}}'],
    )
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["status"] == "success"
    assert output["result"]["ok"] is True


def test_execute_tool_reauth_error(runner, env_vars, httpx_mock):
    _setup_mcp_mocks(httpx_mock, "https://test.merge.dev", "tp_123", "user_456", MCP_CALL_REAUTH)

    result = runner.invoke(
        execute_tool, ["slack__post_message", '{"input": {"channel": "#general"}}']
    )
    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["error_type"] == "reauth_required"


def test_execute_tool_billing_error(runner, env_vars, httpx_mock):
    _setup_mcp_mocks(httpx_mock, "https://test.merge.dev", "tp_123", "user_456", MCP_CALL_BILLING)

    result = runner.invoke(
        execute_tool, ["slack__post_message", '{"input": {"channel": "#general"}}']
    )
    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["error_type"] == "billing_limit_reached"
    assert "billing.example.com" in output["hint"]


def test_execute_tool_invalid_json(runner, env_vars):
    result = runner.invoke(execute_tool, ["slack__post_message", "not-json"])
    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["error_type"] == "invalid_params"


def test_execute_tool_missing_config(runner, monkeypatch):
    monkeypatch.delenv("MERGE_AH_API_KEY", raising=False)
    monkeypatch.delenv("MERGE_AH_TOOL_PACK_ID", raising=False)
    monkeypatch.delenv("MERGE_AH_REGISTERED_USER_ID", raising=False)
    monkeypatch.setattr("merge_cli.config._load_config_file", lambda: {})

    result = runner.invoke(execute_tool, ["some_tool", "{}"])
    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["error_type"] == "config_error"
