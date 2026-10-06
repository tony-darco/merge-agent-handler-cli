"""Tests for merge search-tools command."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from merge_cli.commands.search_tools import search_tools

MCP_URL = "https://test.merge.dev/api/v1/tool-packs/tp_123/registered-users/user_456/mcp"

MCP_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": True}},
        "serverInfo": {"name": "test", "version": "0.1.0"},
    },
}

MCP_SEARCH_SUCCESS = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    [
                        {
                            "name": "post_message",
                            "fully_qualified_name": "slack__post_message",
                            "human_name": "post_message",
                            "description": "Post a message to a Slack channel",
                            "input_schema": {
                                "type": "object",
                                "properties": {"channel": {"type": "string"}},
                            },
                            "relevance_score": 0.95,
                            "reasoning": "Direct match",
                        }
                    ]
                ),
            }
        ],
        "isError": False,
    },
}

MCP_SEARCH_ERROR = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"error": "execution_error", "message": "Search failed"}),
            }
        ],
        "isError": True,
    },
}


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def env_vars(monkeypatch):
    monkeypatch.setenv("MERGE_AH_API_KEY", "pk_test_key")
    monkeypatch.setenv("MERGE_AH_TOOL_PACK_ID", "tp_123")
    monkeypatch.setenv("MERGE_AH_REGISTERED_USER_ID", "user_456")
    monkeypatch.setenv("MERGE_AH_BASE_URL", "https://test.merge.dev")


def _mock_mcp_search(httpx_mock, call_response=MCP_SEARCH_SUCCESS):
    """Mock MCP init + tools/call for search."""
    httpx_mock.add_response(
        url=MCP_URL,
        method="POST",
        json=MCP_INIT,
        headers={"Mcp-Session-Id": "s1"},
    )
    httpx_mock.add_response(
        url=MCP_URL,
        method="POST",
        json=call_response,
        headers={"Mcp-Session-Id": "s1"},
    )


def test_search_tools_success(runner, env_vars, httpx_mock):
    _mock_mcp_search(httpx_mock)

    result = runner.invoke(search_tools, ["send a slack message"])
    assert result.exit_code == 0

    output = json.loads(result.output)
    assert output["total_results"] == 1
    assert output["tools"][0]["name"] == "post_message"
    assert "relevance_score" not in output["tools"][0]
    assert "reasoning" not in output["tools"][0]
    assert "hint" in output


def test_search_tools_no_schema(runner, env_vars, httpx_mock):
    _mock_mcp_search(httpx_mock)

    result = runner.invoke(search_tools, ["send a slack message", "--schema", "none"])
    assert result.exit_code == 0

    output = json.loads(result.output)
    assert "input_schema" not in output["tools"][0]


def test_search_tools_with_connector_filter(runner, env_vars, httpx_mock):
    _mock_mcp_search(httpx_mock)

    result = runner.invoke(
        search_tools, ["send a message", "--connector", "slack", "--max-results", "5"]
    )
    assert result.exit_code == 0

    # Verify the MCP request body includes connector_slugs and max_results
    requests = httpx_mock.get_requests(url=MCP_URL)
    # Second request is tools/call (first is init)
    call_body = json.loads(requests[1].content)
    assert call_body["method"] == "tools/call"
    args = call_body["params"]["arguments"]
    assert args["connector_slugs"] == ["slack"]
    assert args["max_results"] == 5


def test_search_tools_missing_config(runner, monkeypatch):
    monkeypatch.delenv("MERGE_AH_API_KEY", raising=False)
    monkeypatch.delenv("MERGE_AH_TOOL_PACK_ID", raising=False)
    monkeypatch.delenv("MERGE_AH_REGISTERED_USER_ID", raising=False)

    result = runner.invoke(search_tools, ["test"])
    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["error_type"] == "config_error"


def test_search_tools_api_error(runner, env_vars, httpx_mock):
    _mock_mcp_search(httpx_mock, call_response=MCP_SEARCH_ERROR)

    result = runner.invoke(search_tools, ["test"])
    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["error_type"] == "api_error"
