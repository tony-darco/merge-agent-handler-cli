"""## Tony addition to the merge agent handler api ##

merge logs — filter and tail tool-call logs, joined to agent turns by trace/turn id.

Why two sources: the logs endpoint is Enterprise-only, so most people will work from a
dashboard export (CSV) or saved JSON. The filter/group/format logic is pure and shared, and
the API path just fetches records and hands them to the same code.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from datetime import date, datetime, time, timezone

import click

from merge_cli.client import MergeClientError
from merge_cli.common import add_common_options, get_client
from merge_cli.output import config_error, emit, error_response

# Fields that arrive as JSON-encoded strings (always in CSV, and in the API response).
_JSON_FIELDS = ("tool_args", "result", "headers")


def parse_time(value: str, *, end_of_day: bool = False) -> datetime:
    """Parse an ISO-8601 timestamp or date into an aware UTC datetime.

    Why not compare strings: `2026-10-06T10:00` sorts after `2026-10-06`, `...:00Z` sorts
    after `...:00.123Z`, and `Z` differs from `+00:00`, so text comparison misorders them.
    Python 3.10's fromisoformat rejects `Z` and fractions that are not 3 or 6 digits, so both
    are normalised first. A date-only value means the whole day: start for --since, end for
    --until (`end_of_day`). Naive times are taken as UTC. Raises ValueError if unparseable.
    """
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.combine(
            date.fromisoformat(value),
            time.max if end_of_day else time.min,
            tzinfo=timezone.utc,
        )
    value = re.sub(r"[zZ]$", "+00:00", value)
    value = re.sub(r"\.(\d+)", lambda m: "." + m.group(1)[:6].ljust(6, "0"), value, count=1)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _safe_time(value: str | None) -> datetime | None:
    try:
        return parse_time(value) if value else None
    except ValueError:
        return None


def filter_logs(
    logs: list[dict],
    *,
    tool: str | None = None,
    status: str | None = None,
    trace_id: str | None = None,
    turn_id: str | None = None,
    error_reason: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    """Keep records matching every given filter. `tool` is a full name or connector prefix.

    The prefix must end at `__` so `slack` does not match an unrelated `slackbot__ping`.
    `since`/`until` are inclusive and compared as datetimes (see parse_time); a record whose
    `started_at` cannot be parsed is dropped when either is given. Returns a new list; the
    input is never mutated.
    """
    lower = parse_time(since) if since else None
    upper = parse_time(until, end_of_day=True) if until else None

    def keep(log: dict) -> bool:
        name = log.get("tool_name") or ""
        if tool and name != tool and not name.startswith(f"{tool}__"):
            return False
        if status and log.get("status") != status:
            return False
        if trace_id and log.get("client_trace_id") != trace_id:
            return False
        if turn_id and log.get("turn_id") != turn_id:
            return False
        if error_reason and log.get("error_reason") != error_reason:
            return False
        if lower or upper:
            started = _safe_time(log.get("started_at"))
            if started is None or (lower and started < lower) or (upper and started > upper):
                return False
        return True

    return [log for log in logs if keep(log)]


def group_by_turn(logs: list[dict]) -> dict[tuple, list[dict]]:
    """Group records by (client_trace_id, turn_id), in first-seen order.

    Turn ids alone can repeat across traces, so the pair is the key; this is what lets one
    agent turn's tool calls be read together.
    """
    groups: dict[tuple, list[dict]] = {}
    for log in logs:
        groups.setdefault((log.get("client_trace_id"), log.get("turn_id")), []).append(log)
    return groups


def format_log_line(log: dict) -> str:
    """One greppable line per record, ids included so output can be joined to an agent session."""
    return (
        f"{log.get('started_at')} {log.get('status')} {log.get('tool_name')} "
        f"trace={log.get('client_trace_id')} turn={log.get('turn_id')}"
    )


def parse_json_fields(log: dict) -> dict:
    """Decode `tool_args`, `result` and `headers` when they are JSON strings.

    Why: they come back as strings, so callers must not assume they are already objects.
    Anything that is not valid JSON is left as the original string; empty CSV cells become None.
    """
    out = dict(log)
    for key in _JSON_FIELDS:
        value = out.get(key)
        if value == "":
            out[key] = None
        elif isinstance(value, str):
            try:
                out[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return out


def read_records(text: str) -> list[dict]:
    """Parse a saved API response, JSON array, JSONL, or a CSV export.

    Why whole-text JSON first: a pretty-printed `{"results": [...]}` from curl spans many
    lines and starts with `{`, which a line-by-line JSONL reader would choke on. JSONL is the
    fallback when the whole text is not one JSON value.
    """
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if text.startswith(("[", "{")):
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            data = list(csv.DictReader(io.StringIO(text)))
    if isinstance(data, dict):
        results = data.get("results", data.get("data"))
        data = results if isinstance(results, list) else [data]
    return [parse_json_fields(r) for r in data]


@click.command("logs")
@click.argument("source", type=click.File("r"), required=False)
@click.option("--tool", help="Tool name; the API matches partially, files match connector prefix.")
@click.option("--connector", help="Only tools from this connector (matched on the tool name).")
@click.option("--status", help="Only this status (e.g. error).")
@click.option("--error-reason", help="e.g. blocked_by_security_rule, reauth_required.")
@click.option("--trace-id", help="Only this client trace id.")
@click.option("--turn-id", help="Only this agent turn.")
@click.option("--since", help="Only records started at/after this ISO-8601 time.")
@click.option("--until", help="Only records started at/before this ISO-8601 time.")
@click.option(
    "--tail",
    type=click.IntRange(min=1),
    help="Show only the last N records. The API is oldest-first, so use --since to avoid "
    "paging through all 30 days.",
)
@click.option("--group", is_flag=True, help="Group output by (trace, turn).")
def logs_cmd(
    source,
    tool,
    connector,
    status,
    error_reason,
    trace_id,
    turn_id,
    since,
    until,
    tail,
    group,
    api_key,
    tool_pack_id,
    registered_user_id,
    base_url,
):
    """Show tool-call logs.

    With SOURCE (a JSON, JSONL or CSV file; "-" for stdin) filters run locally. Without it,
    logs are fetched from the API (Enterprise plan, last 30 days).
    """
    try:
        since_dt = parse_time(since) if since else None
        until_dt = parse_time(until, end_of_day=True) if until else None
    except ValueError as exc:
        raise click.BadParameter(f"not an ISO-8601 date or time: {exc}") from exc

    if source is not None:
        try:
            records = read_records(source.read())
        except (json.JSONDecodeError, csv.Error) as exc:
            raise click.ClickException(f"Could not parse log file: {exc}") from exc
        records = filter_logs(
            records,
            tool=tool,
            status=status,
            trace_id=trace_id,
            turn_id=turn_id,
            error_reason=error_reason,
            since=since,
            until=until,
        )
    else:
        client, errors = get_client(
            api_key=api_key,
            tool_pack_id=tool_pack_id,
            registered_user_id=registered_user_id,
            base_url=base_url,
        )
        if errors or client is None:
            emit(config_error(errors))
            sys.exit(1)
        params = {
            "tool_name": tool,
            "status": status,
            "error_reason": error_reason,
            "client_trace_id": trace_id,
            "turn_id": turn_id,
            "created_after": since_dt.isoformat() if since_dt else None,
            "created_before": until_dt.isoformat() if until_dt else None,
        }
        try:
            with client:
                records = [parse_json_fields(r) for r in client.list_tool_call_logs(params)]
        except MergeClientError as exc:
            message = str(exc)
            if exc.status_code == 403:
                message += " (Tool-call logs need an Enterprise plan; pass an exported file.)"
            emit(error_response(message, error_type="api_error"))
            sys.exit(1)

    if connector:
        records = filter_logs(records, tool=connector)
    if tail:
        records = records[-tail:]

    if group:
        for (trace, turn), items in group_by_turn(records).items():
            click.echo(f"== trace={trace} turn={turn}")
            for log in items:
                click.echo(f"  {format_log_line(log)}")
    else:
        for log in records:
            click.echo(format_log_line(log))


logs_cmd = add_common_options(logs_cmd)
