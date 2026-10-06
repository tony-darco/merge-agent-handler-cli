"""Tests for output formatting utilities."""

from __future__ import annotations

import json

from merge_cli.output import config_error, emit, error_response, warn


def test_emit_writes_json(capsys):
    emit({"key": "value"})
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"key": "value"}


def test_emit_pretty_prints(capsys):
    emit({"a": 1})
    captured = capsys.readouterr()
    assert "\n" in captured.out  # indented JSON has newlines


def test_warn_writes_to_stderr(capsys):
    warn("something happened")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[merge] something happened" in captured.err


def test_error_response_defaults():
    result = error_response("Something broke")
    assert result["status"] == "error"
    assert result["error_type"] == "error"
    assert result["message"] == "Something broke"
    assert result["hint"] == "Something broke"
    assert result["result"] is None


def test_error_response_custom():
    result = error_response("bad input", error_type="validation", hint="Fix it")
    assert result["error_type"] == "validation"
    assert result["hint"] == "Fix it"


def test_config_error():
    result = config_error(["Missing API key", "Missing user ID"])
    assert result["error_type"] == "config_error"
    assert "Missing API key" in result["message"]
    assert "Missing user ID" in result["message"]
    assert "merge agent signup" in result["hint"]
