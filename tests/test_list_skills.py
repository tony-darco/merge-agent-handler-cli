"""Tests for merge list-skills command."""

from __future__ import annotations

import json

from merge_cli.commands.list_skills import list_skills

MCP_LIST_SUCCESS = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "skills": [
                            {
                                "slug": "expense-report",
                                "name": "Expense Report",
                                "description": "File an expense report.",
                                "referenced_connectors": [],
                                "status": "published",
                            }
                        ]
                    }
                ),
            }
        ],
        "isError": False,
    },
}

MCP_LIST_ERROR = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [{"type": "text", "text": json.dumps({"error": "execution_error"})}],
        "isError": True,
    },
}


def test_list_skills_success(runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments):
    setup_mcp_mocks(httpx_mock, MCP_LIST_SUCCESS)

    result = runner.invoke(list_skills, [])

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["status"] == "success"
    assert output["result"]["skills"][0]["slug"] == "expense-report"
    # No --keyword → no keyword sent (list everything).
    assert call_arguments(httpx_mock) == {}


def test_list_skills_passes_keyword(runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments):
    setup_mcp_mocks(httpx_mock, MCP_LIST_SUCCESS)

    result = runner.invoke(list_skills, ["--keyword", "expense"])

    assert result.exit_code == 0
    assert call_arguments(httpx_mock) == {"keyword": "expense"}


def test_list_skills_forwards_empty_keyword(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments
):
    # An explicitly provided empty --keyword is forwarded, not silently dropped.
    setup_mcp_mocks(httpx_mock, MCP_LIST_SUCCESS)

    result = runner.invoke(list_skills, ["--keyword", ""])

    assert result.exit_code == 0
    assert call_arguments(httpx_mock) == {"keyword": ""}


def test_list_skills_tool_error_exits_nonzero(runner, env_vars, httpx_mock, setup_mcp_mocks):
    # A tool-returned error → error envelope, exit 1.
    setup_mcp_mocks(httpx_mock, MCP_LIST_ERROR)

    result = runner.invoke(list_skills, [])

    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["status"] == "error"


def test_list_skills_not_authenticated(runner, httpx_mock):
    # No env vars / config (see _clean_merge_env) → auth error before any request.
    result = runner.invoke(list_skills, [])

    assert result.exit_code == 1
    output = json.loads(result.output)
    # Assert the config/auth path specifically, so a stray network_error can't
    # make this pass for the wrong reason.
    assert output["error_type"] == "config_error"


MCP_LIST_REJECTED = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "skills": [
                            {
                                "slug": "expense-report",
                                "name": "Expense Report",
                                "description": "File an expense report.",
                                "referenced_connectors": [],
                                "status": "rejected",
                                "version_number": None,
                                "rejection_reason": "Needs an approval step.",
                            }
                        ]
                    }
                ),
            }
        ],
        "isError": False,
    },
}


def test_list_skills_passes_one_status(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments
):
    setup_mcp_mocks(httpx_mock, MCP_LIST_SUCCESS)

    result = runner.invoke(list_skills, ["--status", "draft"])

    assert result.exit_code == 0
    assert call_arguments(httpx_mock) == {"status": ["draft"]}


def test_list_skills_repeats_into_a_list(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments
):
    setup_mcp_mocks(httpx_mock, MCP_LIST_SUCCESS)

    result = runner.invoke(list_skills, ["--status", "draft", "--status", "rejected"])

    assert result.exit_code == 0
    assert call_arguments(httpx_mock) == {"status": ["draft", "rejected"]}


def test_list_skills_combines_status_and_keyword(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments
):
    setup_mcp_mocks(httpx_mock, MCP_LIST_SUCCESS)

    result = runner.invoke(list_skills, ["--keyword", "expense", "--status", "draft"])

    assert result.exit_code == 0
    assert call_arguments(httpx_mock) == {"keyword": "expense", "status": ["draft"]}


def test_list_skills_omits_status_when_unset(
    runner, env_vars, httpx_mock, setup_mcp_mocks, call_arguments
):
    """Omitted, never sent as null — the server's default is what a flagless
    call has always meant."""
    setup_mcp_mocks(httpx_mock, MCP_LIST_SUCCESS)

    result = runner.invoke(list_skills, [])

    assert result.exit_code == 0
    assert "status" not in call_arguments(httpx_mock)


def test_list_skills_rejects_an_unknown_status(runner, env_vars, httpx_mock):
    """click refuses before any network call, so a typo costs no round trip."""
    result = runner.invoke(list_skills, ["--status", "deprecated"])

    assert result.exit_code == 2
    assert httpx_mock.get_requests() == []


def test_list_skills_surfaces_status_and_rejection_reason(
    runner, env_vars, httpx_mock, setup_mcp_mocks
):
    """A caller asking for rejected work gets the reason without a second
    command; the envelope passes server fields through untouched."""
    setup_mcp_mocks(httpx_mock, MCP_LIST_REJECTED)

    result = runner.invoke(list_skills, ["--status", "rejected"])

    assert result.exit_code == 0
    skill = json.loads(result.output)["result"]["skills"][0]
    assert skill["status"] == "rejected"
    assert skill["rejection_reason"] == "Needs an approval step."
    assert skill["version_number"] is None


def test_list_skills_surfaces_status_on_published_rows(
    runner, env_vars, httpx_mock, setup_mcp_mocks
):
    setup_mcp_mocks(httpx_mock, MCP_LIST_SUCCESS)

    result = runner.invoke(list_skills, [])

    assert json.loads(result.output)["result"]["skills"][0]["status"] == "published"
