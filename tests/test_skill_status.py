"""Tests for merge unpublish-skill / republish-skill commands."""

from __future__ import annotations

import json

import pytest

from merge_cli.commands.skill_status import republish_skill, unpublish_skill

MCP_UPDATE_SUCCESS = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "skill": {
                            "slug": "expense-report",
                            "name": "Expense Report",
                            "is_active": False,
                            "changed": True,
                        }
                    }
                ),
            }
        ],
        "isError": False,
    },
}

MCP_UPDATE_ERROR = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "error": "update_skill_failed",
                        "message": "Skill 'expense-report' has never been published.",
                    }
                ),
            }
        ],
        "isError": True,
    },
}


def test_unpublish_sends_is_active_false(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments
):
    setup_mcp_mocks(httpx_mock, MCP_UPDATE_SUCCESS)

    result = runner.invoke(unpublish_skill, ["expense-report"])

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["status"] == "success"
    assert output["result"]["skill"]["changed"] is True
    assert call_arguments(httpx_mock) == {"skill": "expense-report", "is_active": False}


def test_republish_sends_is_active_true(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments
):
    setup_mcp_mocks(httpx_mock, MCP_UPDATE_SUCCESS)

    result = runner.invoke(republish_skill, ["expense-report"])

    assert result.exit_code == 0
    assert call_arguments(httpx_mock) == {"skill": "expense-report", "is_active": True}


@pytest.mark.parametrize("command", [unpublish_skill, republish_skill])
def test_both_commands_call_the_one_update_skill_tool(
    runner, env_vars, httpx_mock, setup_mcp_mocks, command
):
    """Two verbs, one server tool — a rename on either side has to break here."""
    setup_mcp_mocks(httpx_mock, MCP_UPDATE_SUCCESS)

    runner.invoke(command, ["expense-report"])

    assert json.loads(httpx_mock.get_requests()[-1].content)["params"]["name"] == "update_skill"


def test_a_missing_slug_is_rejected_before_any_request(runner, env_vars, httpx_mock):
    result = runner.invoke(unpublish_skill, [])

    assert result.exit_code == 2
    assert httpx_mock.get_requests() == []


def test_tool_error_exits_nonzero_with_the_server_message(
    runner, env_vars, httpx_mock, setup_mcp_mocks
):
    """The refusal text is how a caller learns to use publish-skill instead."""
    setup_mcp_mocks(httpx_mock, MCP_UPDATE_ERROR)

    result = runner.invoke(unpublish_skill, ["expense-report"])

    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["status"] == "error"
    assert "never been published" in output["message"]


def test_unpublish_not_authenticated(runner, httpx_mock):
    result = runner.invoke(unpublish_skill, ["expense-report"])

    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["error_type"] == "config_error"


def test_republish_not_authenticated(runner, httpx_mock):
    result = runner.invoke(republish_skill, ["expense-report"])

    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["error_type"] == "config_error"
