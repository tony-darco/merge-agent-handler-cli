"""## Tony addition to the merge agent handler api ##

merge lint — static scan of a Tool Pack for risky or confusing tools.

Why: an agent picks tools from names and descriptions alone, so destructive tools, vague
scope and near-duplicate descriptions are the main ways it ends up doing the wrong thing."""

from __future__ import annotations

import re
import sys
from itertools import combinations

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response

READ_VERBS = {
    "list", "get", "search", "read", "find", "fetch", "retrieve", "view", "query",
    "describe", "show", "check", "lookup",
}  # fmt: skip
MUTATING_VERBS = {
    "post", "create", "send", "update", "add", "write", "set", "upload", "edit", "modify",
    "reply", "insert", "patch", "put", "move", "assign", "invite", "publish", "submit",
    "schedule", "comment", "run", "trigger", "execute", "deploy", "approve",
}  # fmt: skip
DESTRUCTIVE_VERBS = {
    "delete", "remove", "archive", "purge", "destroy", "drop", "revoke", "cancel",
    "terminate", "wipe", "clear", "truncate", "transfer", "refund", "void", "charge", "close",
    "disable",
}  # fmt: skip
# Why these are destructive: money movement and closing/disabling are hard to undo. run,
# trigger, execute, deploy and approve are mutating: they act, but are not inherently lossy.
STOPWORDS = {
    "a", "an", "the", "to", "of", "in", "on", "for", "and", "or", "with", "new", "this",
    "that", "is", "are", "by", "from", "as", "at", "be",
}  # fmt: skip
SEVERITY_RANK = {"info": 0, "medium": 1, "high": 2}


def classify_tool(tool: dict) -> str:
    """Return read_only | mutating | destructive | unknown.

    MCP annotations win when present because the server knows the real behaviour. Otherwise
    the first word of the tool part of the name (after `__`) is matched against verb lists;
    the connector prefix is skipped so a connector called `delete_it` cannot taint its tools.
    Destructive verbs are checked first so the riskiest reading wins on any ambiguity.
    """
    annotations = tool.get("annotations") or {}
    read_only = annotations.get("readOnlyHint")
    destructive = annotations.get("destructiveHint")
    if read_only is True:
        return "read_only"
    if destructive is True:
        return "destructive"

    name = tool.get("name", "")
    tool_part = name.split("__", 1)[1] if "__" in name else name
    verb = tool_part.split("_", 1)[0].lower()
    if verb in DESTRUCTIVE_VERBS:
        kind = "destructive"
    elif verb in MUTATING_VERBS:
        kind = "mutating"
    elif verb in READ_VERBS:
        kind = "read_only"
    else:
        kind = "unknown"

    # An explicit False is also the server's word: the name may not overrule it.
    if destructive is False and kind == "destructive":
        kind = "mutating"
    if read_only is False and kind in ("read_only", "unknown"):
        kind = "mutating"
    return kind


def classification_counts(tools: list[dict]) -> dict:
    """How each tool was classified: by server annotation, by verb heuristic, or not at all.

    Why: annotations are the server's own word; the verb heuristic is a guess from a name.
    If most tools rely on the guess, the findings should be read as a guess too.
    """
    counts = {"annotations": 0, "heuristic": 0, "unknown": 0}
    for tool in tools:
        annotations = tool.get("annotations") or {}
        if any(isinstance(annotations.get(h), bool) for h in ("readOnlyHint", "destructiveHint")):
            counts["annotations"] += 1
        elif classify_tool(tool) == "unknown":
            counts["unknown"] += 1
        else:
            counts["heuristic"] += 1
    if counts["heuristic"] + counts["unknown"] > counts["annotations"]:
        counts["warning"] = (
            "Most tools were classified by a verb heuristic on their names, not by server "
            "annotations; treat read_only/mutating/destructive findings as a guess."
        )
    return counts


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", (text or "").lower())) - STOPWORDS


def find_overlaps(tools: list[dict], threshold: float) -> list[dict]:
    """Pairs of tools whose description word sets have Jaccard similarity >= threshold.

    Why Jaccard on words: it needs no embeddings or network, is deterministic and easy to
    explain. Stopwords are dropped first because boilerplate like "create a new X in Y" would
    otherwise make unrelated tools look alike. Empty descriptions never match.
    """
    words = {t["name"]: _words(t.get("description", "")) for t in tools}
    pairs = []
    for a, b in combinations(sorted(words), 2):
        if not words[a] or not words[b]:
            continue
        similarity = len(words[a] & words[b]) / len(words[a] | words[b])
        if similarity >= threshold:
            pairs.append({"tools": [a, b], "similarity": similarity})
    return pairs


def _required_params(tool: dict) -> list[str]:
    """Required params, whether top-level or nested under an `input` object.

    Why both: Agent Handler tools usually wrap params as {properties: {input: {required}}}
    (the same shape list-tools unwraps). Reading only the top level would make every
    destructive tool look parameterless and trigger broad_scope.
    """
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    nested = (schema.get("properties") or {}).get("input")
    if isinstance(nested, dict) and "properties" in nested:
        return nested.get("required") or []
    return schema.get("required") or []


def lint_tools(tools: list[dict], overlap_threshold: float = 0.6) -> list[dict]:
    """Return findings: {tool, rule, severity, message}.

    Overlap is reported once per pair, on the first tool, so one problem is one finding.
    `broad_scope` is limited to destructive tools: a mutating tool with no required params
    is noisy, but a destructive one can act on everything.
    """
    findings: list[dict] = []

    def add(tool: str, rule: str, severity: str, message: str) -> None:
        findings.append({"tool": tool, "rule": rule, "severity": severity, "message": message})

    for tool in tools:
        name = tool["name"]
        kind = classify_tool(tool)
        if kind == "destructive":
            add(name, "destructive", "high", f"{name} is destructive.")
            if not _required_params(tool):
                add(
                    name,
                    "broad_scope",
                    "high",
                    f"{name} is destructive but has no required parameters to narrow its target.",
                )
        elif kind == "mutating":
            add(name, "mutating", "info", f"{name} modifies data.")

    for pair in find_overlaps(tools, overlap_threshold):
        first, second = pair["tools"]
        add(
            first,
            "overlap",
            "medium",
            f"{first} has a description similar to {second} "
            f"(similarity {pair['similarity']:.2f}); this can confuse tool selection.",
        )
    return findings


@click.command("lint")
@click.option(
    "--fail-on",
    type=click.Choice(["high", "medium", "info"]),
    help="Exit 1 if any finding is at or above this severity (for CI).",
)
@click.option(
    "--connector", multiple=True, help="Only lint tools from this connector (repeatable)."
)
@click.option(
    "--overlap-threshold",
    default=0.6,
    type=click.FloatRange(0.0, 1.0),
    help="Jaccard similarity at which two descriptions count as overlapping.",
)
def lint_cmd(
    connector: tuple[str, ...],
    overlap_threshold: float,
    fail_on: str | None,
    api_key: str | None,
    tool_pack_id: str | None,
    registered_user_id: str | None,
    base_url: str | None,
):
    """Scan the Tool Pack for destructive tools, overlapping descriptions and broad scope."""
    client, errors = get_client(
        api_key=api_key,
        tool_pack_id=tool_pack_id,
        registered_user_id=registered_user_id,
        base_url=base_url,
    )
    if errors or client is None:
        emit(config_error(errors))
        sys.exit(1)

    try:
        with client:
            tools = client.list_tools()
    except MergeClientError as exc:
        emit(error_response(str(exc), error_type="api_error"))
        sys.exit(1)

    if connector:
        prefixes = tuple(f"{c}__" for c in connector)
        tools = [t for t in tools if t.get("name", "").startswith(prefixes)]

    findings = lint_tools(tools, overlap_threshold)
    summary = {"tools": len(tools)}
    for severity in ("high", "medium", "info"):
        summary[severity] = sum(f["severity"] == severity for f in findings)
    emit(
        {
            "summary": summary,
            "classification": classification_counts(tools),
            "findings": findings,
        }
    )
    if fail_on and any(SEVERITY_RANK[f["severity"]] >= SEVERITY_RANK[fail_on] for f in findings):
        sys.exit(1)


lint_cmd = add_common_options(lint_cmd)
