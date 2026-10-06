"""merge update — self-update via pip or pipx."""

from __future__ import annotations

import shutil
import subprocess
import sys

import click


def _detect_installer() -> str:
    """Detect whether merge-api was installed via pipx or pip."""
    if shutil.which("pipx"):
        # Check if merge-api is in pipx list
        try:
            result = subprocess.run(
                ["pipx", "list", "--short"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if "merge-api" in result.stdout:
                return "pipx"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return "pip"


@click.command()
def update():
    """Update merge-api to the latest version."""
    installer = _detect_installer()

    if installer == "pipx":
        cmd = ["pipx", "upgrade", "merge-api"]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "merge-api"]

    click.echo(f"Updating via {installer}: {' '.join(cmd)}")
    subprocess.run(cmd)
