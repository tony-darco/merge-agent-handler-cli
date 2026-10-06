"""Shared fixtures for the skill command tests."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

BASE_URL = "https://test.merge.dev"
TOOL_PACK_ID = "tp_123"
USER_ID = "user_456"

MCP_INIT_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": True}},
        "serverInfo": {"name": "ToolPack MCP Server", "version": "0.1.0"},
    },
}


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def env_vars(monkeypatch):
    monkeypatch.setenv("MERGE_AH_API_KEY", "pk_test_key")
    monkeypatch.setenv("MERGE_AH_TOOL_PACK_ID", TOOL_PACK_ID)
    monkeypatch.setenv("MERGE_AH_REGISTERED_USER_ID", USER_ID)
    monkeypatch.setenv("MERGE_AH_BASE_URL", BASE_URL)


@pytest.fixture
def setup_mcp_mocks():
    """Return a helper that mocks the MCP initialize call, then a tools/call response."""

    def _setup(httpx_mock, call_response):
        url = f"{BASE_URL}/api/v1/tool-packs/{TOOL_PACK_ID}/registered-users/{USER_ID}/mcp"
        headers = {"Mcp-Session-Id": "session-abc"}
        httpx_mock.add_response(url=url, method="POST", json=MCP_INIT_RESPONSE, headers=headers)
        httpx_mock.add_response(url=url, method="POST", json=call_response, headers=headers)

    return _setup


@pytest.fixture
def call_arguments():
    """Return a helper that reads the `arguments` of the last tools/call request."""

    def _read(httpx_mock):
        return json.loads(httpx_mock.get_requests()[-1].content)["params"]["arguments"]

    return _read
