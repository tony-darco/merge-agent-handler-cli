"""## Tony addition to the merge agent handler api ##

merge eval — tool-selection eval harness: precision, recall, F1 and wrong-tool hits.

Why: tool search is the core of Agent Handler, and without a score there is no way to tell
whether a change to descriptions or ranking helped. Cases live in JSONL so they are easy to
diff and grow."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response


@dataclass
class Case:
    id: str
    intent: str
    expected: list[str]
    connectors: list[str] = field(default_factory=list)
    # tool -> tools that must also be selected before it counts (multi-step cases)
    requires: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class CaseResult:
    id: str
    returned: list[str]
    precision: float
    recall: float
    wrong_tools: list[str]
    f1: float = 0.0
    hit: bool = False
    reciprocal_rank: float = 0.0


def load_cases(path: Path) -> list[Case]:
    """Read a JSONL dataset, one case per line. Blank lines are skipped."""
    cases: list[Case] = []

    for i, line in enumerate(path.read_text().splitlines()):
        line_number = i + 1
        line = line.strip()

        if not line:
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise click.ClickException(f"Error decoding JSON on line {line_number}: {e}") from e

        required_fields = ["id", "intent", "expected"]
        expected = obj.get("expected")
        if "expected" in obj and (
            not isinstance(expected, list) or not all(isinstance(t, str) for t in expected)
        ):
            raise click.ClickException(
                f"Field 'expected' must be a list of tool names on line {line_number}."
            )
        for name in required_fields:
            if name not in obj:
                raise click.ClickException(
                    f"Missing required field '{name}' on line {line_number}."
                )
            # An empty `expected` would make recall undefined, so reject it up front.
            if name == "expected" and not obj[name]:
                raise click.ClickException(f"Field '{name}' cannot be empty on line {line_number}.")

        try:
            case = Case(
                id=obj["id"],
                intent=obj["intent"],
                expected=obj["expected"],
                connectors=obj.get("connectors", []),
                requires=obj.get("requires", {}),
            )
            cases.append(case)
        except Exception as e:
            raise click.ClickException(
                f"Error creating Case object on line {line_number}: {e}"
            ) from e

    return cases


def f1_score(precision: float, recall: float) -> float:
    """Harmonic mean; 0.0 when both are 0 so an empty result never divides by zero."""
    total = precision + recall
    return 2 * precision * recall / total if total else 0.0


def score_case(case: Case, returned: list[str]) -> CaseResult:
    """Scoring one case.

    `relevant` drives precision, multi-step tasks need prerequisite
    tools (e.g. search before reply). Penalising them as wrong picks would punish correct
    behaviour. Recall is stricter: a step only counts when its prerequisites were also found.

    """
    unique = list(dict.fromkeys(returned))
    got = set(unique)
    expected = set(case.expected)
    relevant = expected.union(*(case.requires.get(t, []) for t in expected))

    found = {t for t in expected & got if all(r in got for r in case.requires.get(t, []))}
    precision = len(got & relevant) / len(got) if got else 0.0
    recall = len(found) / len(expected) if expected else 0.0

    # Precision is capped at relevant/k, so on a single-answer case it shrinks as k grows and
    # says little alone. hit and reciprocal_rank (1/rank of the first expected tool) show
    # whether the right tool was found and how high.
    rank = next((i for i, t in enumerate(unique, 1) if t in expected), None)

    return CaseResult(
        id=case.id,
        returned=returned,
        precision=precision,
        recall=recall,
        wrong_tools=[t for t in unique if t not in relevant],
        f1=f1_score(precision, recall),
        hit=rank is not None,
        reciprocal_rank=1 / rank if rank else 0.0,
    )


def aggregate(results: list[CaseResult]) -> dict:
    """Macro-average precision/recall/F1/hit rate/MRR plus total wrong-tool hits."""
    n = len(results)
    return {
        "cases": n,
        "precision": sum(r.precision for r in results) / n if n else 0.0,
        "recall": sum(r.recall for r in results) / n if n else 0.0,
        "f1": sum(f1_score(r.precision, r.recall) for r in results) / n if n else 0.0,
        "hit_rate": sum(r.hit for r in results) / n if n else 0.0,
        "mrr": sum(r.reciprocal_rank for r in results) / n if n else 0.0,
        "wrong_tool_hits": sum(len(r.wrong_tools) for r in results),
    }


def tool_names(search_response: dict) -> list[str]:
    """Pull tool names from a client.search_tools() response."""
    names: list[str] = []
    for tool in search_response.get("tools", []):
        name = tool.get("fully_qualified_name") or tool.get("name")
        if name:
            names.append(name)
    return names


@click.command("eval")
@click.argument("dataset", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--max-results",
    default=5,
    type=click.IntRange(1, 50),
    help="Top-k returned per search (1-50).",
)
@click.option(
    "--k",
    "ks",
    multiple=True,
    type=click.IntRange(1, 50),
    help="Also report scores at this k (repeatable, e.g. --k 2 --k 5 --k 10).",
)
def eval_cmd(
    dataset: Path,
    max_results: int,
    ks: tuple[int, ...],
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """Score tool selection for the cases in DATASET (JSONL)."""
    client, errors = get_client(
        api_key=api_key,
        tool_pack_id=tool_pack_id,
        registered_user_id=registered_user_id,
        base_url=base_url,
    )
    if errors or client is None:
        emit(config_error(errors))
        sys.exit(1)

    cases = load_cases(dataset)
    if not cases:
        raise click.ClickException(f"{dataset} contains no cases.")
    # One search per case at the largest k needed; smaller k reuse its top-k prefix because
    # results are ranked, so scoring at several k costs no extra API calls.
    fetch = max([max_results, *ks])
    searches: list[tuple[Case, list[str]]] = []
    try:
        with client:
            for case in cases:
                data = client.search_tools(
                    case.intent,
                    connector_slugs=case.connectors or None,
                    max_results=fetch,
                )
                searches.append((case, tool_names(data)))
    except MergeClientError as exc:
        emit(error_response(str(exc), error_type="api_error"))
        sys.exit(1)

    results = [score_case(case, names[:max_results]) for case, names in searches]
    # `max_results` is stated next to the scores: recall is capped by it, so a score without
    # its k is easy to misread.
    summary = {"max_results": max_results, **aggregate(results)}
    out = {"summary": summary, "cases": [r.__dict__ for r in results]}
    if ks:
        out["by_k"] = {
            str(k): aggregate([score_case(case, names[:k]) for case, names in searches])
            for k in sorted(set(ks))
        }
    emit(out)


eval_cmd = add_common_options(eval_cmd)
