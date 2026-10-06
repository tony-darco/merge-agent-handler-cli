"""Tests for the MergeClient HTTP client."""

from __future__ import annotations

import json

import pytest

from merge_cli.client import MergeClient, MergeClientError
from merge_cli.config import AgentHandlerConfig

BASE_URL = "https://test.merge.dev"
MCP_URL = f"{BASE_URL}/api/v1/tool-packs/tp_123/registered-users/user_456/mcp"


@pytest.fixture
def config():
    return AgentHandlerConfig(
        api_key="pk_test",
        tool_pack_id="tp_123",
        registered_user_id="user_456",
        base_url=BASE_URL,
    )


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
                "name": "slack__post_message",
                "description": "Post a message",
                "inputSchema": {"type": "object"},
            },
        ]
    },
}


class TestMergeClientSession:
    def test_context_manager(self, config, httpx_mock):
        with MergeClient(config) as client:
            assert client.config == config
        # No error means close() was called

    def test_initializes_mcp_session(self, config, httpx_mock):
        httpx_mock.add_response(
            url=MCP_URL,
            method="POST",
            json=MCP_INIT,
            headers={"Mcp-Session-Id": "session-xyz"},
        )
        httpx_mock.add_response(
            url=MCP_URL,
            method="POST",
            json=MCP_LIST,
            headers={"Mcp-Session-Id": "session-xyz"},
        )
        with MergeClient(config) as client:
            tools = client.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "slack__post_message"


class TestSearchTools:
    def test_search_returns_results(self, config, httpx_mock):
        httpx_mock.add_response(
            url=MCP_URL,
            method="POST",
            json=MCP_INIT,
            headers={"Mcp-Session-Id": "s1"},
        )
        httpx_mock.add_response(
            url=MCP_URL,
            method="POST",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                [
                                    {
                                        "name": "test_tool",
                                        "fully_qualified_name": "c__test_tool",
                                        "human_name": "test_tool",
                                        "description": "A tool",
                                        "input_schema": {},
                                        "relevance_score": 0.9,
                                        "reasoning": "match",
                                    },
                                ]
                            ),
                        }
                    ],
                    "isError": False,
                },
            },
            headers={"Mcp-Session-Id": "s1"},
        )
        with MergeClient(config) as client:
            result = client.search_tools("test")
        assert result["total_results"] == 1
        assert "relevance_score" not in result["tools"][0]

    def test_search_error(self, config, httpx_mock):
        httpx_mock.add_response(
            url=MCP_URL,
            method="POST",
            json=MCP_INIT,
            headers={"Mcp-Session-Id": "s1"},
        )
        httpx_mock.add_response(
            url=MCP_URL,
            method="POST",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"error": "execution_error", "message": "Search failed"}
                            ),
                        }
                    ],
                    "isError": True,
                },
            },
            headers={"Mcp-Session-Id": "s1"},
        )
        with MergeClient(config) as client:
            with pytest.raises(MergeClientError, match="Search failed"):
                client.search_tools("test")


class TestGetToolSchema:
    def test_found(self, config, httpx_mock):
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
        with MergeClient(config) as client:
            tool = client.get_tool_schema("slack__post_message")
        assert tool is not None
        assert tool["name"] == "slack__post_message"

    def test_not_found(self, config, httpx_mock):
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
        with MergeClient(config) as client:
            tool = client.get_tool_schema("nonexistent")
        assert tool is None


class TestParseToolResult:
    @pytest.fixture
    def client(self, config):
        return MergeClient(config)

    def test_success(self, client):
        result = client.parse_tool_result(
            {
                "isError": False,
                "content": [{"type": "text", "text": '{"ok": true}'}],
            }
        )
        assert result["status"] == "success"
        assert result["result"]["ok"] is True

    def test_reauth_required(self, client):
        result = client.parse_tool_result(
            {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "error": "reauth_required",
                                "message": "Token expired",
                            }
                        ),
                    }
                ],
            }
        )
        assert result["status"] == "error"
        assert result["error_type"] == "reauth_required"

    def test_billing_limit(self, client):
        result = client.parse_tool_result(
            {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "error": "billing_limit_reached",
                                "message": "Limit hit",
                                "billing_page_url": "https://billing.example.com",
                            }
                        ),
                    }
                ],
            }
        )
        assert result["status"] == "error"
        assert result["error_type"] == "billing_limit_reached"
        assert "billing.example.com" in result["hint"]

    def test_generic_error(self, client):
        result = client.parse_tool_result(
            {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"error": "unknown", "message": "Something broke"}),
                    }
                ],
            }
        )
        assert result["status"] == "error"
        assert result["error_type"] == "unknown"

    def test_empty_content(self, client):
        result = client.parse_tool_result({"isError": False, "content": []})
        assert result["status"] == "success"

    def test_non_json_text(self, client):
        result = client.parse_tool_result(
            {
                "isError": False,
                "content": [{"type": "text", "text": "plain text result"}],
            }
        )
        assert result["status"] == "success"
        assert result["result"]["raw"] == "plain text result"


class TestMCPErrors:
    def test_jsonrpc_error(self, config, httpx_mock):
        httpx_mock.add_response(
            url=MCP_URL,
            method="POST",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32600, "message": "Invalid request"},
            },
            headers={"Mcp-Session-Id": "s1"},
        )
        with MergeClient(config) as client:
            client._session_id = "s1"
            with pytest.raises(MergeClientError, match="Invalid request"):
                client._mcp_request("tools/list")

    def test_http_error(self, config, httpx_mock):
        httpx_mock.add_response(url=MCP_URL, method="POST", status_code=503, text="Unavailable")
        with MergeClient(config) as client:
            client._session_id = "s1"
            with pytest.raises(MergeClientError, match="503"):
                client._mcp_request("tools/list")
