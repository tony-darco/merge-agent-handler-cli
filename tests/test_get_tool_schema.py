"""Tests for merge get-tool-schema command."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from merge_cli.commands.get_tool_schema import get_tool_schema

MCP_URL = "https://test.merge.dev/api/v1/tool-packs/tp_123/registered-users/user_456/mcp"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def env_vars(monkeypatch):
    monkeypatch.setenv("MERGE_AH_API_KEY", "pk_test_key")
    monkeypatch.setenv("MERGE_AH_TOOL_PACK_ID", "tp_123")
    monkeypatch.setenv("MERGE_AH_REGISTERED_USER_ID", "user_456")
    monkeypatch.setenv("MERGE_AH_BASE_URL", "https://test.merge.dev")


MCP_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "serverInfo": {"name": "test", "version": "0.1.0"},
    },
}

MCP_LIST = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "tools": [
            {
                "name": "slack__post_message",
                "description": "Post a message",
                "inputSchema": {
                    "type": "object",
                    "properties": {"channel": {"type": "string"}},
                },
            },
        ]
    },
}


def _mock_mcp(httpx_mock):
    httpx_mock.add_response(
        url=MCP_URL,
        method="POST",
        json=MCP_INIT,
        headers={"Mcp-Session-Id": "s1"},
    )
    httpx_mock.add_response(
        url=MCP_URL,
        method="POST",
        json=MCP_LIST,
        headers={"Mcp-Session-Id": "s1"},
    )


def test_get_tool_schema_success(runner, env_vars, httpx_mock):
    _mock_mcp(httpx_mock)

    result = runner.invoke(get_tool_schema, ["slack__post_message"])
    assert result.exit_code == 0

    output = json.loads(result.output)
    assert output["name"] == "slack__post_message"
    assert "input_schema" in output
    assert "hint" in output


def test_get_tool_schema_not_found(runner, env_vars, httpx_mock):
    _mock_mcp(httpx_mock)

    result = runner.invoke(get_tool_schema, ["nonexistent_tool"])
    assert result.exit_code == 1

    output = json.loads(result.output)
    assert output["error_type"] == "not_found"


def test_get_tool_schema_missing_config(runner, monkeypatch):
    monkeypatch.delenv("MERGE_AH_API_KEY", raising=False)
    monkeypatch.delenv("MERGE_AH_TOOL_PACK_ID", raising=False)
    monkeypatch.delenv("MERGE_AH_REGISTERED_USER_ID", raising=False)
    monkeypatch.setattr("merge_cli.config._load_config_file", lambda: {})

    result = runner.invoke(get_tool_schema, ["some_tool"])
    assert result.exit_code == 1

    output = json.loads(result.output)
    assert output["error_type"] == "config_error"
