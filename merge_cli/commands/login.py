"""merge login — OAuth PKCE login flow."""

from __future__ import annotations

import base64
import hashlib
import html
import secrets
import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import click
import httpx

from merge_cli.config import (
    DEFAULT_BASE_URL,
    _load_config_file,
    save_oauth_config,
)

# Pre-registered client ID — matches the Application created by the backend migration.
# Public client, no secret needed. Same client_id for all CLI users.
MERGE_CLI_CLIENT_ID = "merge-cli"

CALLBACK_PORT_RANGE = range(9400, 9410)
REDIRECT_PATH = "/callback"
CALLBACK_TIMEOUT_SECONDS = 300

_PAGE_STYLE = """\
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    background: #fff;
    color: #0E0D0C;
  }
  .container { text-align: center; }
  h2 {
    font-size: 24px;
    font-weight: 600;
    line-height: 28px;
    letter-spacing: -0.03em;
    margin-bottom: 12px;
  }
  p {
    font-size: 16px;
    font-weight: 400;
    line-height: 26px;
    color: #565551;
  }
</style>
"""


def _success_page() -> bytes:
    return (
        "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
        f"<title>Authentication Successful</title>{_PAGE_STYLE}</head>"
        "<body><div class='container'>"
        "<h2>Authentication successful, you\u2019re all set!</h2>"
        "<p>You can close this window and return to the terminal</p>"
        "</div></body></html>"
    ).encode()


def _error_page(error_message: str) -> bytes:
    safe_msg = html.escape(error_message)
    return (
        "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
        f"<title>Authentication Failed</title>{_PAGE_STYLE}</head>"
        "<body><div class='container'>"
        "<h2>Authentication failed</h2>"
        f"<p>{safe_msg}</p>"
        "</div></body></html>"
    ).encode()


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _find_open_port() -> int:
    """Find an open port in the callback range."""
    for port in CALLBACK_PORT_RANGE:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise click.ClickException(
        f"Could not find an open port in range "
        f"{CALLBACK_PORT_RANGE.start}-{CALLBACK_PORT_RANGE.stop}"
    )


def _exchange_code(
    base_url: str,
    code: str,
    code_verifier: str,
    client_id: str,
    redirect_uri: str,
) -> tuple[str, str]:
    """Exchange authorization code for tokens. Returns (access_token, refresh_token)."""
    resp = httpx.post(
        f"{base_url}/o/token/",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        },
        timeout=10.0,
    )
    if resp.status_code != 200:
        raise click.ClickException(f"Token exchange failed: {resp.status_code} {resp.text}")

    data = resp.json()
    return data["access_token"], data.get("refresh_token", "")


@click.command()
@click.option("--base-url", default=None, help="Agent Handler base URL")
def login(base_url: str | None):
    """Log in to Agent Handler via browser (OAuth)."""
    file_cfg = _load_config_file()
    resolved_base_url = (
        base_url
        or file_cfg.get("oauth", {}).get("base_url")
        or file_cfg.get("agent_handler", {}).get("base_url")
        or DEFAULT_BASE_URL
    )

    port = _find_open_port()
    redirect_uri = f"http://localhost:{port}{REDIRECT_PATH}"

    code_verifier, code_challenge = _generate_pkce_pair()
    state = secrets.token_urlsafe(32)

    auth_params = urlencode(
        {
            "response_type": "code",
            "client_id": MERGE_CLI_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    auth_url = f"{resolved_base_url}/o/authorize/?{auth_params}"

    auth_code: str | None = None
    auth_error: str | None = None

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code, auth_error
            parsed = urlparse(self.path)

            if parsed.path != REDIRECT_PATH:
                self.send_response(404)
                self.end_headers()
                return

            params = parse_qs(parsed.query)

            returned_state = params.get("state", [None])[0]
            if returned_state != state:
                auth_error = "Invalid state parameter — possible CSRF attack"
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(_error_page("Invalid state parameter."))
                return

            if "code" in params:
                auth_code = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(_success_page())
            elif "error" in params:
                auth_error = params.get("error_description", params["error"])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(_error_page(auth_error))
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    server.timeout = CALLBACK_TIMEOUT_SECONDS

    click.echo("\nOpening browser to log in...\n")
    click.echo(f"If the browser doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    click.echo("Waiting for authorization (press Ctrl+C to cancel)...")
    while auth_code is None and auth_error is None:
        server.handle_request()
        if auth_code is None and auth_error is None:
            # handle_request returned without setting either — timeout
            break
    server.server_close()

    if auth_error:
        raise click.ClickException(f"Authorization denied: {auth_error}")

    if not auth_code:
        raise click.ClickException(
            "No authorization code received. The request timed out. Run `merge login` to try again."
        )

    click.echo("Exchanging authorization code for token...")
    access_token, refresh_token = _exchange_code(
        resolved_base_url, auth_code, code_verifier, MERGE_CLI_CLIENT_ID, redirect_uri
    )

    save_oauth_config(
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=MERGE_CLI_CLIENT_ID,
        base_url=resolved_base_url,
    )

    click.echo("\nLogged in successfully! Tokens saved to ~/.merge/config.json")
