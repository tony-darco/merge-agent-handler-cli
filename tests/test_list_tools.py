"""Tests for merge list-tools command."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from merge_cli.commands.list_tools import list_tools


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

MCP_LIST_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "tools": [
            {
                "name": "slack__post_message",
                "description": "Post a message to a Slack channel",
                "inputSchema": {"type": "object", "properties": {"channel": {"type": "string"}}},
            },
            {
                "name": "slack__list_channels",
                "description": "List Slack channels",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "salesforce__create_lead",
                "description": "Create a new Salesforce lead",
                "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        ]
    },
}


def _setup_list_mocks(httpx_mock):
    url = "https://test.merge.dev/api/v1/tool-packs/tp_123/registered-users/user_456/mcp"
    httpx_mock.add_response(
        url=url,
        method="POST",
        json=MCP_INIT_RESPONSE,
        headers={"Mcp-Session-Id": "session-abc"},
    )
    httpx_mock.add_response(
        url=url,
        method="POST",
        json=MCP_LIST_RESPONSE,
        headers={"Mcp-Session-Id": "session-abc"},
    )


def test_list_tools_compact(runner, env_vars, httpx_mock):
    _setup_list_mocks(httpx_mock)

    result = runner.invoke(list_tools, [])
    assert result.exit_code == 0

    output = json.loads(result.output)
    assert output["total"] == 3
    # Compact mode: only name + description
    tool = output["tools"][0]
    assert "name" in tool
    assert "description" in tool
    assert "inputSchema" not in tool


def test_list_tools_full(runner, env_vars, httpx_mock):
    _setup_list_mocks(httpx_mock)

    result = runner.invoke(list_tools, ["--full"])
    assert result.exit_code == 0

    output = json.loads(result.output)
    assert output["total"] == 3
    # Full mode: includes schema
    assert "inputSchema" in output["tools"][0]


def test_list_tools_connector_filter(runner, env_vars, httpx_mock):
    _setup_list_mocks(httpx_mock)

    result = runner.invoke(list_tools, ["--connector", "slack"])
    assert result.exit_code == 0

    output = json.loads(result.output)
    assert output["total"] == 2
    for tool in output["tools"]:
        assert tool["name"].startswith("slack__")


def test_list_tools_missing_config(runner, monkeypatch):
    monkeypatch.delenv("MERGE_AH_API_KEY", raising=False)
    monkeypatch.delenv("MERGE_AH_TOOL_PACK_ID", raising=False)
    monkeypatch.delenv("MERGE_AH_REGISTERED_USER_ID", raising=False)
    monkeypatch.setattr("merge_cli.config._load_config_file", lambda: {})

    result = runner.invoke(list_tools, [])
    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["error_type"] == "config_error"
