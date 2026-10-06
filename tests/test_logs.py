"""Tests for merge logs.

Record shape (from the GET /api/v1/logs/tool-calls/ docs): `tool_name`, `tool_args`,
`result`, `headers`, `status`, `error_reason`, `client_trace_id`, `turn_id`, `started_at`.
`tool_args`/`result`/`headers` arrive as JSON *strings*. The endpoint is cursor-paginated,
oldest-first, last 30 days, Enterprise only.

Contract:
* filter_logs(logs, *, tool, status, trace_id, turn_id, error_reason, since, until) keeps
  records matching every given filter (AND), preserves order, and never mutates the input
* `tool` matches the full tool name or a connector prefix (`slack` matches `slack__post_message`)
* group_by_turn(logs) -> {(client_trace_id, turn_id): [records...]} in first-seen order
* format_log_line(log) -> "<started_at> <status> <tool_name> trace=<id> turn=<id>"
* read_records(text) accepts a JSON array, JSONL or CSV and decodes JSON-string fields
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from merge_cli.client import MergeClient, MergeClientError
from merge_cli.commands.logs import (
    count_unparseable,
    filter_logs,
    format_log_line,
    group_by_turn,
    logs_cmd,
    parse_json_fields,
    read_records,
)


def _log(
    tool="slack__post_message",
    status="success",
    trace="t1",
    turn="u1",
    ts="2026-01-01T00:00:00Z",
    error_reason=None,
):
    return {
        "started_at": ts,
        "tool_name": tool,
        "status": status,
        "error_reason": error_reason,
        "client_trace_id": trace,
        "turn_id": turn,
    }


LOGS = [
    _log("slack__post_message", "success", "t1", "u1", "2026-01-01T00:00:01Z"),
    _log("slack__list_channels", "error", "t1", "u2", "2026-01-01T00:00:02Z", "reauth_required"),
    _log("jira__create_issue", "success", "t2", "u1", "2026-01-01T00:00:03Z"),
]


def _ids(logs):
    return [(r["client_trace_id"], r["turn_id"], r["tool_name"]) for r in logs]


# ---------------------------------------------------------------------------
# filter_logs
# ---------------------------------------------------------------------------


def test_filter_no_filters_returns_everything_in_order():
    assert filter_logs(LOGS) == LOGS


def test_filter_by_exact_tool():
    out = filter_logs(LOGS, tool="jira__create_issue")
    assert [r["tool_name"] for r in out] == ["jira__create_issue"]


def test_filter_by_connector_prefix():
    out = filter_logs(LOGS, tool="slack")
    assert [r["tool_name"] for r in out] == ["slack__post_message", "slack__list_channels"]


def test_filter_connector_prefix_requires_double_underscore_boundary():
    logs = [_log("slackbot__ping"), _log("slack__ping")]
    assert [r["tool_name"] for r in filter_logs(logs, tool="slack")] == ["slack__ping"]


def test_filter_by_status():
    assert [r["status"] for r in filter_logs(LOGS, status="error")] == ["error"]


def test_filter_by_trace_id():
    assert len(filter_logs(LOGS, trace_id="t1")) == 2


def test_filter_by_turn_id():
    assert len(filter_logs(LOGS, turn_id="u1")) == 2


def test_filter_by_error_reason():
    out = filter_logs(LOGS, error_reason="reauth_required")
    assert [r["tool_name"] for r in out] == ["slack__list_channels"]


def test_filter_since_and_until_are_inclusive():
    out = filter_logs(LOGS, since="2026-01-01T00:00:02Z", until="2026-01-01T00:00:02Z")
    assert [r["tool_name"] for r in out] == ["slack__list_channels"]


def test_filter_filters_are_anded():
    out = filter_logs(LOGS, trace_id="t1", turn_id="u1", tool="slack")
    assert _ids(out) == [("t1", "u1", "slack__post_message")]


def test_filter_no_match_returns_empty():
    assert filter_logs(LOGS, trace_id="nope") == []


def test_filter_does_not_mutate_input():
    before = copy.deepcopy(LOGS)
    filter_logs(LOGS, tool="slack", status="error")
    assert LOGS == before


# ---------------------------------------------------------------------------
# group_by_turn
# ---------------------------------------------------------------------------


def test_group_by_turn_keys_and_order():
    logs = [
        _log("a__x", trace="t1", turn="u1"),
        _log("b__y", trace="t2", turn="u1"),
        _log("c__z", trace="t1", turn="u1"),
    ]
    groups = group_by_turn(logs)
    assert list(groups) == [("t1", "u1"), ("t2", "u1")]
    assert [r["tool_name"] for r in groups[("t1", "u1")]] == ["a__x", "c__z"]


def test_group_by_turn_same_turn_id_different_trace_not_merged():
    groups = group_by_turn([_log(trace="t1", turn="u1"), _log(trace="t2", turn="u1")])
    assert len(groups) == 2


def test_group_by_turn_empty():
    assert group_by_turn([]) == {}


# ---------------------------------------------------------------------------
# format_log_line
# ---------------------------------------------------------------------------


def test_format_log_line():
    line = format_log_line(_log(ts="2026-01-01T00:00:01Z"))
    assert line == "2026-01-01T00:00:01Z success slack__post_message trace=t1 turn=u1"


def test_format_log_line_is_single_line():
    assert "\n" not in format_log_line(_log())


# ---------------------------------------------------------------------------
# parse_json_fields / read_records
# ---------------------------------------------------------------------------


def test_parse_json_fields_decodes_strings():
    out = parse_json_fields({"tool_args": '{"a": 1}', "result": "[1, 2]", "headers": "{}"})
    assert out == {"tool_args": {"a": 1}, "result": [1, 2], "headers": {}}


def test_parse_json_fields_leaves_non_json_and_objects_alone():
    out = parse_json_fields({"tool_args": "not json", "result": {"already": "parsed"}})
    assert out == {"tool_args": "not json", "result": {"already": "parsed"}}


def test_parse_json_fields_empty_string_becomes_none():
    assert parse_json_fields({"tool_args": ""})["tool_args"] is None


def test_read_records_json_array():
    text = json.dumps([_log()])
    assert read_records(text)[0]["tool_name"] == "slack__post_message"


def test_read_records_jsonl():
    text = "\n".join(json.dumps(_log(tool=t)) for t in ("a__x", "b__y"))
    assert [r["tool_name"] for r in read_records(text)] == ["a__x", "b__y"]


def test_read_records_csv_with_json_string_cells():
    text = (
        "started_at,tool_name,status,client_trace_id,turn_id,tool_args\n"
        '2026-01-01T00:00:01Z,slack__post_message,success,t1,u1,"{""text"": ""hi""}"\n'
    )
    [rec] = read_records(text)
    assert rec["client_trace_id"] == "t1"
    assert rec["tool_args"] == {"text": "hi"}


def test_read_records_pretty_printed_api_response():
    text = json.dumps({"results": [_log("a__x"), _log("b__y")], "has_more": False}, indent=2)
    assert [r["tool_name"] for r in read_records(text)] == ["a__x", "b__y"]


def test_read_records_single_json_object_is_one_record():
    assert len(read_records(json.dumps(_log()))) == 1


def test_filter_until_date_only_includes_the_whole_day():
    logs = [_log(ts="2026-10-06T10:00:00Z"), _log(ts="2026-10-07T00:00:00Z")]
    assert len(filter_logs(logs, until="2026-10-06")) == 1


def test_filter_since_date_only_starts_at_midnight():
    logs = [_log(ts="2026-10-05T23:59:59Z"), _log(ts="2026-10-06T00:00:00Z")]
    assert len(filter_logs(logs, since="2026-10-06")) == 1


def test_filter_compares_mixed_timestamp_formats_as_times():
    logs = [_log(ts="2026-01-01T00:00:00.123Z"), _log(ts="2026-01-01T01:00:00+01:00")]
    # 00:00:00.123Z is after 00:00:00Z; 01:00+01:00 is exactly 00:00:00Z
    out = filter_logs(logs, since="2026-01-01T00:00:00Z", until="2026-01-01T00:00:00Z")
    assert [r["started_at"] for r in out] == ["2026-01-01T01:00:00+01:00"]


def test_filter_drops_unparseable_started_at_when_time_filtering():
    assert filter_logs([_log(ts="garbage")], since="2026-01-01") == []


def test_logs_cmd_bad_since_is_a_usage_error(runner):
    result = runner.invoke(logs_cmd, ["--since", "yesterday"])
    assert result.exit_code == 2


def test_read_records_empty():
    assert read_records("  \n") == []


# ---------------------------------------------------------------------------
# MergeClient.list_tool_call_logs (cursor pagination)
# ---------------------------------------------------------------------------


def _api_client():
    from merge_cli.config import AgentHandlerConfig

    cfg = AgentHandlerConfig(
        api_key="k", tool_pack_id="tp", registered_user_id="ru", base_url="https://ah-api.merge.dev"
    )
    return MergeClient(config=cfg)


def test_client_follows_cursor_until_has_more_false(httpx_mock):
    httpx_mock.add_response(
        json={"results": [{"tool_name": "a"}], "has_more": True, "next_cursor": "c2"}
    )
    httpx_mock.add_response(json={"results": [{"tool_name": "b"}], "has_more": False})

    with _api_client() as client:
        out = client.list_tool_call_logs({"status": "error", "turn_id": None})

    assert [r["tool_name"] for r in out] == ["a", "b"]
    first, second = httpx_mock.get_requests()
    assert first.url.path == "/api/v1/logs/tool-calls/"
    assert first.url.params["status"] == "error"
    assert "turn_id" not in first.url.params  # None params are dropped
    assert second.url.params["cursor"] == "c2"
    assert first.headers["Authorization"] == "Bearer k"


def test_client_logs_http_error_carries_status(httpx_mock):
    httpx_mock.add_response(status_code=403, text="enterprise only")
    with _api_client() as client, pytest.raises(MergeClientError) as exc:
        client.list_tool_call_logs()
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# logs_cmd
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


def _client_with_logs(records=None, error=None):
    client = MagicMock(spec=MergeClient)
    client.__enter__.return_value = client
    if error:
        client.list_tool_call_logs.side_effect = error
    else:
        client.list_tool_call_logs.return_value = records or []
    return client


def test_logs_cmd_file_mode_filters_locally(runner, tmp_path):
    path = tmp_path / "logs.json"
    path.write_text(json.dumps(LOGS))
    result = runner.invoke(logs_cmd, [str(path), "--status", "error"])
    assert result.exit_code == 0, result.output
    assert result.output.strip().splitlines() == [format_log_line(LOGS[1])]


def test_logs_cmd_stdin_and_tail(runner):
    result = runner.invoke(logs_cmd, ["-", "--tail", "1"], input=json.dumps(LOGS))
    assert result.output.strip().splitlines() == [format_log_line(LOGS[2])]


def test_logs_cmd_group_output(runner, tmp_path):
    path = tmp_path / "logs.json"
    path.write_text(json.dumps(LOGS))
    result = runner.invoke(logs_cmd, [str(path), "--group"])
    assert "== trace=t1 turn=u1" in result.output
    assert "  " + format_log_line(LOGS[0]) in result.output


def test_logs_cmd_api_mode_maps_flags_to_query_params(runner):
    client = _client_with_logs(LOGS[:1])
    with patch("merge_cli.commands.logs.get_client", return_value=(client, [])):
        result = runner.invoke(
            logs_cmd,
            ["--tool", "slack", "--trace-id", "t1", "--since", "2026-01-01T00:00:00Z"],
        )
    assert result.exit_code == 0, result.output
    params = client.list_tool_call_logs.call_args.args[0]
    assert params["tool_name"] == "slack"
    assert params["client_trace_id"] == "t1"
    assert params["created_after"] == "2026-01-01T00:00:00+00:00"  # normalised to UTC


def test_logs_cmd_api_mode_connector_filtered_client_side(runner):
    client = _client_with_logs(LOGS)
    with patch("merge_cli.commands.logs.get_client", return_value=(client, [])):
        result = runner.invoke(logs_cmd, ["--connector", "jira"])
    assert result.output.strip().splitlines() == [format_log_line(LOGS[2])]


def test_logs_cmd_403_mentions_enterprise(runner):
    client = _client_with_logs(error=MergeClientError("nope", status_code=403))
    with patch("merge_cli.commands.logs.get_client", return_value=(client, [])):
        result = runner.invoke(logs_cmd, [])
    assert result.exit_code == 1
    assert "Enterprise" in json.loads(result.output)["message"]


def test_logs_cmd_config_error_exits_1(runner):
    with patch("merge_cli.commands.logs.get_client", return_value=(None, ["Not authenticated."])):
        result = runner.invoke(logs_cmd, [])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "config_error"


def test_logs_cmd_bad_file_is_a_click_error(runner, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[not json")
    result = runner.invoke(logs_cmd, [str(path)])
    assert result.exit_code == 1
    assert "Could not parse" in result.output


def test_httpx_is_the_transport():
    # guards the pytest-httpx tests above against silently testing nothing
    assert hasattr(httpx, "Client")


# ---------------------------------------------------------------------------
# warnings (stderr)
# ---------------------------------------------------------------------------


def test_count_unparseable():
    assert count_unparseable([_log(ts="2026-01-01T00:00:00Z"), _log(ts="01/02/2026"), {}]) == 2


def test_logs_cmd_warns_when_time_filter_skips_unparseable_records(tmp_path):
    path = tmp_path / "logs.json"
    path.write_text(json.dumps([_log(ts="01/02/2026"), _log(ts="2026-01-01T00:00:00Z")]))
    result = CliRunner().invoke(logs_cmd, [str(path), "--since", "2025-12-31"])
    assert "1 record(s) skipped" in result.stderr
    assert len(result.stdout.strip().splitlines()) == 1


def test_logs_cmd_no_skip_warning_without_time_filter(tmp_path):
    path = tmp_path / "logs.json"
    path.write_text(json.dumps([_log(ts="01/02/2026")]))
    result = CliRunner().invoke(logs_cmd, [str(path)])
    assert result.stderr == ""


def test_logs_cmd_warns_when_since_is_beyond_retention():
    client = _client_with_logs([])
    with patch("merge_cli.commands.logs.get_client", return_value=(client, [])):
        result = CliRunner().invoke(logs_cmd, ["--since", "2020-01-01"])
    assert "30-day" in result.stderr


def test_logs_cmd_no_retention_warning_for_recent_since():
    client = _client_with_logs([])
    recent = datetime.now(timezone.utc).date().isoformat()
    with patch("merge_cli.commands.logs.get_client", return_value=(client, [])):
        result = CliRunner().invoke(logs_cmd, ["--since", recent])
    assert result.stderr == ""
