"""Tests for merge lint.

Contract (the tests below are the spec). Tools are the dicts from MCP `tools/list`:
`name` (`connector__tool`), `description`, `inputSchema` (or `input_schema`), and optionally
`annotations` with the MCP hints `readOnlyHint` / `destructiveHint`.

* classify_tool -> "read_only" | "mutating" | "destructive" | "unknown"
    1. annotations win when present: readOnlyHint=True -> read_only,
       destructiveHint=True -> destructive
    2. otherwise heuristic on the first word of the tool part of the name
       (after `__`, split on `_`)
* find_overlaps(tools, threshold) -> [{"tools": [a, b], "similarity": float}], where
  similarity is the Jaccard index of lowercase description words (stopwords removed);
  pairs are sorted by name,
  only pairs with similarity >= threshold are returned
* lint_tools -> list of findings {"tool", "rule", "severity", "message"}; rules:
    destructive  (severity "high")   tool classified destructive
    mutating     (severity "info")   tool classified mutating
    broad_scope  (severity "high")   destructive tool with no required params
    overlap      (severity "medium") one finding per overlapping pair, on the first tool
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from merge_cli.client import MergeClient, MergeClientError
from merge_cli.commands.lint import classify_tool, find_overlaps, lint_cmd, lint_tools


def _tool(name, description="", required=None, annotations=None):
    t = {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": {}, "required": required or []},
    }
    if annotations is not None:
        t["annotations"] = annotations
    return t


# ---------------------------------------------------------------------------
# classify_tool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["slack__list_channels", "jira__get_issue", "gmail__search_messages", "drive__read_file"],
)
def test_classify_read_only_verbs(name):
    assert classify_tool(_tool(name)) == "read_only"


@pytest.mark.parametrize(
    "name",
    ["slack__post_message", "jira__create_issue", "gmail__send_email", "jira__update_issue"],
)
def test_classify_mutating_verbs(name):
    assert classify_tool(_tool(name)) == "mutating"


@pytest.mark.parametrize(
    "name",
    ["jira__delete_issue", "drive__remove_file", "slack__archive_channel", "crm__purge_contacts"],
)
def test_classify_destructive_verbs(name):
    assert classify_tool(_tool(name)) == "destructive"


def test_classify_unknown_verb():
    assert classify_tool(_tool("acme__frobnicate")) == "unknown"


def test_classify_uses_only_the_tool_part_of_the_name():
    # connector named "delete_it" must not make a read tool destructive
    assert classify_tool(_tool("delete_it__list_things")) == "read_only"


def test_classify_annotation_read_only_overrides_name():
    t = _tool("jira__delete_issue", annotations={"readOnlyHint": True})
    assert classify_tool(t) == "read_only"


def test_classify_annotation_destructive_overrides_name():
    t = _tool("jira__get_issue", annotations={"destructiveHint": True})
    assert classify_tool(t) == "destructive"


def test_classify_empty_annotations_fall_back_to_heuristic():
    assert classify_tool(_tool("jira__get_issue", annotations={})) == "read_only"


# ---------------------------------------------------------------------------
# find_overlaps
# ---------------------------------------------------------------------------


def test_overlap_identical_descriptions():
    tools = [
        _tool("a__one", "Send a message to a channel"),
        _tool("b__two", "Send a message to a channel"),
    ]
    out = find_overlaps(tools, threshold=0.6)
    assert out == [{"tools": ["a__one", "b__two"], "similarity": 1.0}]


def test_overlap_partial_similarity_value():
    # words: {send,urgent,message} vs {send,urgent,note} -> 2 shared / 4 total = 0.5
    tools = [_tool("a__one", "Send urgent message"), _tool("b__two", "Send urgent note")]
    out = find_overlaps(tools, threshold=0.5)
    assert out[0]["similarity"] == pytest.approx(0.5)


def test_overlap_below_threshold_excluded():
    tools = [_tool("a__one", "Send a message"), _tool("b__two", "Delete an invoice")]
    assert find_overlaps(tools, threshold=0.6) == []


def test_overlap_is_case_insensitive():
    tools = [_tool("a__one", "Send A Message"), _tool("b__two", "send a message")]
    assert find_overlaps(tools, threshold=0.9)[0]["similarity"] == 1.0


def test_overlap_pair_reported_once_sorted_by_name():
    tools = [_tool("z__t", "same words here"), _tool("a__t", "same words here")]
    assert find_overlaps(tools, threshold=0.6)[0]["tools"] == ["a__t", "z__t"]


def test_overlap_empty_descriptions_never_match():
    tools = [_tool("a__one", ""), _tool("b__two", "")]
    assert find_overlaps(tools, threshold=0.0) == []


def test_overlap_single_tool():
    assert find_overlaps([_tool("a__one", "x")], threshold=0.0) == []


# ---------------------------------------------------------------------------
# lint_tools
# ---------------------------------------------------------------------------


def _rules(findings, tool=None):
    return sorted(f["rule"] for f in findings if tool is None or f["tool"] == tool)


def test_lint_read_only_tool_has_no_findings():
    assert lint_tools([_tool("slack__list_channels", "List channels")]) == []


def test_lint_flags_mutating_as_info():
    findings = lint_tools([_tool("slack__post_message", "Post", required=["text"])])
    assert [(f["rule"], f["severity"]) for f in findings] == [("mutating", "info")]


def test_lint_flags_destructive_as_high():
    findings = lint_tools([_tool("jira__delete_issue", "Delete", required=["issue_id"])])
    assert [(f["rule"], f["severity"]) for f in findings] == [("destructive", "high")]


def test_lint_broad_scope_destructive_without_required_params():
    findings = lint_tools([_tool("crm__purge_contacts", "Purge", required=[])])
    assert _rules(findings) == ["broad_scope", "destructive"]
    broad = next(f for f in findings if f["rule"] == "broad_scope")
    assert broad["severity"] == "high"


def test_lint_broad_scope_not_raised_for_mutating_without_params():
    findings = lint_tools([_tool("slack__post_message", "Post", required=[])])
    assert _rules(findings) == ["mutating"]


def test_lint_reads_input_schema_snake_case_key():
    t = {
        "name": "jira__delete_issue",
        "description": "Delete",
        "input_schema": {"type": "object", "required": ["issue_id"]},
    }
    assert _rules(lint_tools([t])) == ["destructive"]


def test_lint_reports_overlap_on_first_tool():
    tools = [
        _tool("a__list_x", "Return every item in the workspace"),
        _tool("b__list_y", "Return every item in the workspace"),
    ]
    findings = lint_tools(tools, overlap_threshold=0.6)
    assert [(f["tool"], f["rule"], f["severity"]) for f in findings] == [
        ("a__list_x", "overlap", "medium")
    ]
    assert "b__list_y" in findings[0]["message"]


def test_lint_message_names_the_tool():
    findings = lint_tools([_tool("jira__delete_issue", "Delete", required=["id"])])
    assert "jira__delete_issue" in findings[0]["message"]


def test_lint_empty_pack():
    assert lint_tools([]) == []


# ---------------------------------------------------------------------------
# lint_cmd (client mocked, same pattern as test_authenticate.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


def _client_with_tools(tools=None, error=None) -> MagicMock:
    client = MagicMock(spec=MergeClient)
    client.__enter__.return_value = client
    if error:
        client.list_tools.side_effect = error
    else:
        client.list_tools.return_value = tools or []
    return client


def test_lint_cmd_outputs_findings_and_summary(runner):
    client = _client_with_tools(
        [
            _tool("slack__list_channels", "List channels"),
            _tool("slack__post_message", "Post a message", required=["text"]),
            _tool("crm__purge_contacts", "Purge contacts", required=[]),
        ]
    )
    with patch("merge_cli.commands.lint.get_client", return_value=(client, [])):
        result = runner.invoke(lint_cmd, [])

    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["summary"] == {"tools": 3, "high": 2, "medium": 0, "info": 1}
    assert {f["rule"] for f in out["findings"]} == {"mutating", "destructive", "broad_scope"}


def test_lint_cmd_connector_filter(runner):
    client = _client_with_tools(
        [
            _tool("slack__post_message", "Post", required=["text"]),
            _tool("jira__delete_issue", "Delete", required=["id"]),
        ]
    )
    with patch("merge_cli.commands.lint.get_client", return_value=(client, [])):
        result = runner.invoke(lint_cmd, ["--connector", "jira"])

    out = json.loads(result.output)
    assert out["summary"]["tools"] == 1
    assert {f["tool"] for f in out["findings"]} == {"jira__delete_issue"}


def test_lint_cmd_overlap_threshold_option(runner):
    client = _client_with_tools(
        [_tool("a__t", "Send urgent message"), _tool("b__t", "Send urgent note")]  # similarity 0.5
    )
    with patch("merge_cli.commands.lint.get_client", return_value=(client, [])):
        loose = runner.invoke(lint_cmd, ["--overlap-threshold", "0.4"])
        strict = runner.invoke(lint_cmd, ["--overlap-threshold", "0.9"])

    assert [f["rule"] for f in json.loads(loose.output)["findings"]] == ["overlap"]
    assert json.loads(strict.output)["findings"] == []


def test_lint_cmd_config_error_exits_1(runner):
    with patch("merge_cli.commands.lint.get_client", return_value=(None, ["Not authenticated."])):
        result = runner.invoke(lint_cmd, [])

    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "config_error"


def test_lint_cmd_api_error_exits_1(runner):
    client = _client_with_tools(error=MergeClientError("boom"))
    with patch("merge_cli.commands.lint.get_client", return_value=(client, [])):
        result = runner.invoke(lint_cmd, [])

    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "api_error"


def test_lint_cmd_reports_classification_basis_and_warns_on_heuristic(runner):
    client = _client_with_tools(
        [
            _tool("a__get_x", annotations={"readOnlyHint": True}),
            _tool("a__post_y", required=["t"]),
            _tool("a__list_z"),
            _tool("a__frobnicate"),
        ]
    )
    with patch("merge_cli.commands.lint.get_client", return_value=(client, [])):
        result = runner.invoke(lint_cmd, [])

    classification = json.loads(result.output)["classification"]
    assert (classification["annotations"], classification["heuristic"]) == (1, 2)
    assert classification["unknown"] == 1
    assert "guess" in classification["warning"]


def test_lint_cmd_no_warning_when_annotations_dominate(runner):
    tool = _tool("a__x", annotations={"destructiveHint": True}, required=["i"])
    client = _client_with_tools([tool])
    with patch("merge_cli.commands.lint.get_client", return_value=(client, [])):
        result = runner.invoke(lint_cmd, [])
    assert "warning" not in json.loads(result.output)["classification"]


def test_classify_explicit_false_hints_override_heuristic():
    assert classify_tool(_tool("jira__delete_issue", annotations={"destructiveHint": False})) == (
        "mutating"
    )
    assert classify_tool(_tool("jira__get_issue", annotations={"readOnlyHint": False})) == (
        "mutating"
    )


@pytest.mark.parametrize("name", ["pay__refund_charge", "ops__disable_user", "pay__void_invoice"])
def test_classify_extra_destructive_verbs(name):
    assert classify_tool(_tool(name)) == "destructive"


@pytest.mark.parametrize("name", ["ci__run_job", "ci__deploy_app", "hr__approve_request"])
def test_classify_extra_mutating_verbs(name):
    assert classify_tool(_tool(name)) == "mutating"


def test_overlap_ignores_stopword_boilerplate():
    tools = [
        _tool("a__x", "Create a new invoice in the system"),
        _tool("b__y", "Create a new user in the system"),
    ]
    assert find_overlaps(tools, threshold=0.6) == []


def test_lint_reads_required_nested_under_input():
    t = {
        "name": "jira__delete_issue",
        "description": "Delete",
        "inputSchema": {"properties": {"input": {"properties": {}, "required": ["id"]}}},
    }
    assert _rules(lint_tools([t])) == ["destructive"]


def test_classification_counts_explicit_false_as_annotation():
    from merge_cli.commands.lint import classification_counts

    counts = classification_counts([_tool("a__delete_x", annotations={"destructiveHint": False})])
    assert counts["annotations"] == 1


def test_lint_cmd_fail_on_exits_1_when_threshold_met(runner):
    client = _client_with_tools([_tool("jira__delete_issue", required=["id"])])
    with patch("merge_cli.commands.lint.get_client", return_value=(client, [])):
        high = runner.invoke(lint_cmd, ["--fail-on", "high"])
        info_only = runner.invoke(lint_cmd, [])
    assert high.exit_code == 1
    assert info_only.exit_code == 0


def test_lint_cmd_fail_on_high_ignores_lower_severity(runner):
    client = _client_with_tools([_tool("slack__post_message", required=["t"])])
    with patch("merge_cli.commands.lint.get_client", return_value=(client, [])):
        result = runner.invoke(lint_cmd, ["--fail-on", "high"])
    assert result.exit_code == 0
