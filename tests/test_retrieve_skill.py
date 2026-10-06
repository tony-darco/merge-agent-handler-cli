"""Tests for merge retrieve-skill command."""

from __future__ import annotations

import json

from merge_cli.commands.retrieve_skill import retrieve_skill

MCP_RETRIEVE_SUCCESS = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "slug": "expense-report",
                        "name": "Expense Report",
                        "skill_md": "# Body",
                        "manifest": ["SKILL.md"],
                    }
                ),
            }
        ],
        "isError": False,
    },
}

MCP_RETRIEVE_ERROR = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"error": "not_found", "message": "Skill 'nope' not found."}),
            }
        ],
        "isError": True,
    },
}


def test_retrieve_skill_success(runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments):
    setup_mcp_mocks(httpx_mock, MCP_RETRIEVE_SUCCESS)

    result = runner.invoke(retrieve_skill, ["expense-report"])

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["status"] == "success"
    assert output["result"]["skill_md"] == "# Body"
    # No --path → only the slug is sent.
    assert call_arguments(httpx_mock) == {"skill": "expense-report"}


def test_retrieve_skill_passes_path(runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments):
    setup_mcp_mocks(httpx_mock, MCP_RETRIEVE_SUCCESS)

    result = runner.invoke(retrieve_skill, ["expense-report", "--path", "references/notes.md"])

    assert result.exit_code == 0
    assert call_arguments(httpx_mock) == {
        "skill": "expense-report",
        "path": "references/notes.md",
    }


def test_retrieve_skill_forwards_empty_path(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments
):
    # An explicitly provided empty --path is forwarded (server rejects it) rather
    # than silently dropped (which would return the SKILL.md body).
    setup_mcp_mocks(httpx_mock, MCP_RETRIEVE_SUCCESS)

    result = runner.invoke(retrieve_skill, ["expense-report", "--path", ""])

    assert result.exit_code == 0
    assert call_arguments(httpx_mock) == {"skill": "expense-report", "path": ""}


def test_retrieve_skill_tool_error_exits_nonzero(runner, env_vars, httpx_mock, setup_mcp_mocks):
    # A tool-returned error (e.g. unknown slug) → error envelope, exit 1.
    setup_mcp_mocks(httpx_mock, MCP_RETRIEVE_ERROR)

    result = runner.invoke(retrieve_skill, ["nope"])

    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["status"] == "error"


def test_retrieve_skill_requires_slug(runner, env_vars):
    # Missing the required SKILL argument → Click usage error, no request.
    result = runner.invoke(retrieve_skill, [])

    assert result.exit_code != 0
