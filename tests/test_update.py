"""Tests for merge update command."""

from __future__ import annotations

from unittest.mock import patch

from merge_cli.commands.update import _detect_installer


def test_detect_installer_pipx(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/pipx" if x == "pipx" else None)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "merge-api 0.1.0\n"
        assert _detect_installer() == "pipx"


def test_detect_installer_pip(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: None)
    assert _detect_installer() == "pip"


def test_detect_installer_pipx_without_merge(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/pipx" if x == "pipx" else None)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "other-package 1.0.0\n"
        assert _detect_installer() == "pip"
