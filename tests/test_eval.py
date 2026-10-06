"""Tests for merge eval command.

Contract (the tests below are the spec):

* relevant tools  = expected ∪ every tool listed in `requires` for an expected tool
* precision       = |returned ∩ relevant| / |returned|   (0.0 when nothing is returned)
* wrong_tools     = returned − relevant, in returned order, no duplicates
* recall          = found expected / |expected|. An expected tool is "found" only if it was
                    returned AND all of its `requires` were returned too.
* aggregate       = macro-average over cases + total wrong-tool hits
* tool_names      = `fully_qualified_name`, falling back to `name`; ignores requestable_tools
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner

from merge_cli.client import MergeClient, MergeClientError
from merge_cli.commands.eval import (
    Case,
    CaseResult,
    aggregate,
    eval_cmd,
    load_cases,
    score_case,
    tool_names,
)


def test_tool_names_prefers_fully_qualified_name():
    data = {"tools": [{"name": "post_message", "fully_qualified_name": "slack__post_message"}]}
    assert tool_names(data) == ["slack__post_message"]


def test_tool_names_falls_back_to_name():
    assert tool_names({"tools": [{"name": "post_message"}]}) == ["post_message"]


def test_tool_names_preserves_order():
    data = {"tools": [{"name": "b"}, {"name": "a"}, {"name": "c"}]}
    assert tool_names(data) == ["b", "a", "c"]


def test_tool_names_ignores_requestable_tools():
    data = {
        "tools": [{"name": "a"}],
        "requestable_tools": [{"name": "locked"}],
    }
    assert tool_names(data) == ["a"]


def test_tool_names_empty_or_missing():
    assert tool_names({"tools": []}) == []
    assert tool_names({}) == []


# ---------------------------------------------------------------------------
# score_case — single step
# ---------------------------------------------------------------------------


def test_score_perfect_match():
    case = Case(id="c", intent="x", expected=["a", "b"])
    r = score_case(case, ["a", "b"])
    assert r.id == "c"
    assert r.returned == ["a", "b"]
    assert r.precision == 1.0
    assert r.recall == 1.0
    assert r.wrong_tools == []


def test_score_order_does_not_matter():
    case = Case(id="c", intent="x", expected=["a", "b"])
    r = score_case(case, ["b", "a"])
    assert (r.precision, r.recall) == (1.0, 1.0)


def test_score_wrong_tool_hit():
    case = Case(id="c", intent="x", expected=["a"])
    r = score_case(case, ["a", "z"])
    assert r.precision == pytest.approx(0.5)
    assert r.recall == 1.0
    assert r.wrong_tools == ["z"]


def test_score_missed_tool_lowers_recall_not_precision():
    case = Case(id="c", intent="x", expected=["a", "b"])
    r = score_case(case, ["a"])
    assert r.precision == 1.0
    assert r.recall == pytest.approx(0.5)
    assert r.wrong_tools == []


def test_score_all_wrong():
    case = Case(id="c", intent="x", expected=["a"])
    r = score_case(case, ["y", "z"])
    assert r.precision == 0.0
    assert r.recall == 0.0
    assert r.wrong_tools == ["y", "z"]


def test_score_empty_return():
    case = Case(id="c", intent="x", expected=["a"])
    r = score_case(case, [])
    assert r.precision == 0.0
    assert r.recall == 0.0
    assert r.wrong_tools == []


def test_score_duplicates_in_returned_counted_once():
    case = Case(id="c", intent="x", expected=["a"])
    r = score_case(case, ["a", "z", "z"])
    assert r.precision == pytest.approx(0.5)
    assert r.wrong_tools == ["z"]


# ---------------------------------------------------------------------------
# score_case — multi step (requires)
# ---------------------------------------------------------------------------


def test_prerequisite_is_not_a_wrong_hit():
    case = Case(
        id="c",
        intent="x",
        expected=["gmail__reply"],
        requires={"gmail__reply": ["gmail__search_messages"]},
    )
    r = score_case(case, ["gmail__search_messages", "gmail__reply"])
    assert r.wrong_tools == []
    assert r.precision == 1.0
    assert r.recall == 1.0


def test_missing_prerequisite_zeroes_recall_for_that_step():
    case = Case(
        id="c",
        intent="x",
        expected=["gmail__reply"],
        requires={"gmail__reply": ["gmail__search_messages"]},
    )
    r = score_case(case, ["gmail__reply"])
    assert r.recall == 0.0
    assert r.precision == 1.0
    assert r.wrong_tools == []


def test_recall_counts_steps_independently():
    case = Case(
        id="c",
        intent="x",
        expected=["a", "b"],
        requires={"b": ["pre"]},
    )
    # a is found; b is returned but its prerequisite is not
    r = score_case(case, ["a", "b"])
    assert r.recall == pytest.approx(0.5)


def test_prerequisite_of_unreturned_expected_tool_is_still_relevant():
    case = Case(id="c", intent="x", expected=["b"], requires={"b": ["pre"]})
    r = score_case(case, ["pre"])
    assert r.wrong_tools == []
    assert r.precision == 1.0
    assert r.recall == 0.0


def test_requires_for_tool_not_expected_is_ignored():
    case = Case(id="c", intent="x", expected=["a"], requires={"other": ["pre"]})
    r = score_case(case, ["a", "pre"])
    assert r.wrong_tools == ["pre"]


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


def _res(id, precision, recall, wrong=()):
    return CaseResult(
        id=id, returned=[], precision=precision, recall=recall, wrong_tools=list(wrong)
    )


def test_aggregate_macro_average_and_wrong_total():
    out = aggregate(
        [_res("a", 1.0, 1.0), _res("b", 0.5, 0.0, ["z"]), _res("c", 0.0, 0.5, ["x", "y"])]
    )
    assert out["cases"] == 3
    assert out["precision"] == pytest.approx(0.5)
    assert out["recall"] == pytest.approx(0.5)
    assert out["wrong_tool_hits"] == 3
    # macro F1: per-case F1 = 1.0, 0.0, 0.0
    assert out["f1"] == pytest.approx(1 / 3)


def test_score_f1_is_harmonic_mean():
    case = Case(id="c", intent="x", expected=["a", "b"])
    r = score_case(case, ["a", "z"])  # precision 0.5, recall 0.5
    assert r.f1 == pytest.approx(0.5)
    assert score_case(case, []).f1 == 0.0


def test_aggregate_empty():
    out = aggregate([])
    assert out == {
        "cases": 0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "hit_rate": 0.0,
        "mrr": 0.0,
        "wrong_tool_hits": 0,
    }


# ---------------------------------------------------------------------------
# load_cases
# ---------------------------------------------------------------------------


def _write(tmp_path, lines):
    p = tmp_path / "cases.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return p


def test_load_cases_minimal_defaults(tmp_path):
    p = _write(tmp_path, [json.dumps({"id": "c1", "intent": "do x", "expected": ["a"]})])
    cases = load_cases(p)
    assert cases == [Case(id="c1", intent="do x", expected=["a"], connectors=[], requires={})]


def test_load_cases_all_fields(tmp_path):
    obj = {
        "id": "c1",
        "intent": "do x",
        "expected": ["a", "b"],
        "connectors": ["gmail"],
        "requires": {"b": ["a"]},
    }
    cases = load_cases(_write(tmp_path, [json.dumps(obj)]))
    assert cases[0].connectors == ["gmail"]
    assert cases[0].requires == {"b": ["a"]}


def test_load_cases_skips_blank_lines(tmp_path):
    line = json.dumps({"id": "c1", "intent": "x", "expected": ["a"]})
    p = _write(tmp_path, [line, "", "   ", line.replace("c1", "c2")])
    assert [c.id for c in load_cases(p)] == ["c1", "c2"]


def test_load_cases_bad_json_reports_line_number(tmp_path):
    good = json.dumps({"id": "c1", "intent": "x", "expected": ["a"]})
    p = _write(tmp_path, [good, "{not json"])
    with pytest.raises(Exception) as exc:
        load_cases(p)
    assert type(exc.value).__name__ == "ClickException"
    assert "line 2" in str(exc.value.message).lower()


@pytest.mark.parametrize("missing", ["id", "intent", "expected"])
def test_load_cases_missing_required_field(tmp_path, missing):
    obj = {"id": "c1", "intent": "x", "expected": ["a"]}
    del obj[missing]
    with pytest.raises(Exception) as exc:
        load_cases(_write(tmp_path, [json.dumps(obj)]))
    assert type(exc.value).__name__ == "ClickException"
    assert missing in str(exc.value.message)
    assert "line 1" in str(exc.value.message).lower()


def test_load_cases_empty_expected_rejected(tmp_path):
    obj = {"id": "c1", "intent": "x", "expected": []}
    with pytest.raises(Exception) as exc:
        load_cases(_write(tmp_path, [json.dumps(obj)]))
    assert type(exc.value).__name__ == "ClickException"


# ---------------------------------------------------------------------------
# eval_cmd end to end (client mocked)
# ---------------------------------------------------------------------------


def _client_with_search(responses: dict[str, list[str]] | None = None, error=None) -> MagicMock:
    """A MergeClient whose search_tools returns the tool names mapped to each intent."""
    client = MagicMock(spec=MergeClient)
    client.__enter__.return_value = client
    if error:
        client.search_tools.side_effect = error
    else:
        client.search_tools.side_effect = lambda intent, **kw: {
            "tools": [{"name": n} for n in (responses or {}).get(intent, [])]
        }
    return client


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def dataset(tmp_path):
    rows = [
        {"id": "post", "intent": "post to slack", "expected": ["slack__post_message"]},
        {
            "id": "reply",
            "intent": "reply to email",
            "expected": ["gmail__reply"],
            "connectors": ["gmail"],
            "requires": {"gmail__reply": ["gmail__search"]},
        },
    ]
    return _write(tmp_path, [json.dumps(r) for r in rows])


def test_eval_cmd_outputs_summary_and_cases(runner, dataset):
    client = _client_with_search(
        {
            "post to slack": ["slack__post_message", "slack__list_channels"],
            "reply to email": ["gmail__search", "gmail__reply"],
        }
    )
    with patch("merge_cli.commands.eval.get_client", return_value=(client, [])):
        result = runner.invoke(eval_cmd, [str(dataset)])

    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["summary"]["cases"] == 2
    assert out["summary"]["wrong_tool_hits"] == 1
    assert out["summary"]["recall"] == 1.0
    assert out["summary"]["precision"] == pytest.approx(0.75)
    by_id = {c["id"]: c for c in out["cases"]}
    assert by_id["post"]["wrong_tools"] == ["slack__list_channels"]
    assert by_id["reply"]["wrong_tools"] == []


def test_eval_cmd_passes_connectors_and_max_results(runner, dataset):
    client = _client_with_search()
    with patch("merge_cli.commands.eval.get_client", return_value=(client, [])):
        result = runner.invoke(eval_cmd, [str(dataset), "--max-results", "3"])

    assert result.exit_code == 0, result.output
    assert client.search_tools.call_args_list == [
        call("post to slack", connector_slugs=None, max_results=3),
        call("reply to email", connector_slugs=["gmail"], max_results=3),
    ]


def test_eval_cmd_config_error_exits_1(runner, dataset):
    with patch("merge_cli.commands.eval.get_client", return_value=(None, ["Not authenticated."])):
        result = runner.invoke(eval_cmd, [str(dataset)])

    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "config_error"


def test_eval_cmd_api_error_exits_1(runner, dataset):
    client = _client_with_search(error=MergeClientError("boom"))
    with patch("merge_cli.commands.eval.get_client", return_value=(client, [])):
        result = runner.invoke(eval_cmd, [str(dataset)])

    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "api_error"


def test_eval_cmd_missing_dataset_is_usage_error(runner):
    result = runner.invoke(eval_cmd, ["/nonexistent/cases.jsonl"])
    assert result.exit_code == 2


def test_eval_cmd_summary_states_max_results(runner, dataset):
    client = _client_with_search()
    with patch("merge_cli.commands.eval.get_client", return_value=(client, [])):
        result = runner.invoke(eval_cmd, [str(dataset), "--max-results", "3"])
    assert json.loads(result.output)["summary"]["max_results"] == 3


def test_eval_cmd_reports_by_k_from_one_search_per_case(runner, dataset):
    client = _client_with_search(
        {
            "post to slack": ["slack__list_channels", "slack__post_message"],
            "reply to email": ["gmail__search", "gmail__reply"],
        }
    )
    with patch("merge_cli.commands.eval.get_client", return_value=(client, [])):
        result = runner.invoke(
            eval_cmd, [str(dataset), "--max-results", "2", "--k", "1", "--k", "2"]
        )

    out = json.loads(result.output)
    assert out["by_k"]["1"]["recall"] == 0.0  # the right post tool is ranked 2nd
    assert out["by_k"]["2"]["recall"] == 1.0
    assert client.search_tools.call_count == 2  # one search per case, not per k


def test_score_hit_and_reciprocal_rank():
    case = Case(id="c", intent="x", expected=["a"])
    assert (
        score_case(case, ["z", "y", "a"]).hit,
        score_case(case, ["z", "y", "a"]).reciprocal_rank,
    ) == (
        True,
        pytest.approx(1 / 3),
    )
    miss = score_case(case, ["z"])
    assert (miss.hit, miss.reciprocal_rank) == (False, 0.0)


def test_aggregate_hit_rate_and_mrr():
    hit = CaseResult(
        id="a", returned=[], precision=0, recall=0, wrong_tools=[], hit=True, reciprocal_rank=0.5
    )
    miss = CaseResult(id="b", returned=[], precision=0, recall=0, wrong_tools=[])
    out = aggregate([hit, miss])
    assert out["hit_rate"] == 0.5
    assert out["mrr"] == 0.25


def test_load_cases_expected_must_be_a_list_of_strings(tmp_path):
    line = json.dumps({"id": "c1", "intent": "x", "expected": "slack__post_message"})
    with pytest.raises(Exception) as exc:
        load_cases(_write(tmp_path, [line]))
    assert type(exc.value).__name__ == "ClickException"
    assert "list" in str(exc.value.message)


def test_eval_cmd_empty_dataset_is_an_error(runner, tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n")
    client = _client_with_search()
    with patch("merge_cli.commands.eval.get_client", return_value=(client, [])):
        result = runner.invoke(eval_cmd, [str(path)])
    assert result.exit_code != 0
    assert "no cases" in result.output


def test_eval_cmd_max_results_out_of_range_is_usage_error(runner, dataset):
    assert runner.invoke(eval_cmd, [str(dataset), "--max-results", "0"]).exit_code == 2
    assert runner.invoke(eval_cmd, [str(dataset), "--max-results", "51"]).exit_code == 2
