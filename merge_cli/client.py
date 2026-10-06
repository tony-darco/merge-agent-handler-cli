"""HTTP client for Merge Agent Handler API."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from merge_cli import __version__
from merge_cli.config import AgentHandlerConfig, OAuthConfig, save_oauth_config

DEFAULT_TIMEOUT = 60.0


class MergeClientError(Exception):
    """Raised when the API returns an unexpected error."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class MergeClient:
    """Synchronous HTTP client for Agent Handler endpoints.

    Supports two auth modes:
    - OAuth: uses /mcp/ endpoint with Bearer token (from `merge login`)
    - API key: uses /api/v1/tool-packs/.../mcp endpoint (from `merge agent signup`)
    """

    def __init__(
        self,
        config: AgentHandlerConfig | None = None,
        oauth_config: OAuthConfig | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        common_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"merge-cli/{__version__}",
        }

        if oauth_config is not None:
            self._auth_mode = "oauth"
            self._oauth_config = oauth_config
            self._base_url = oauth_config.base_url.rstrip("/")
            self._http = httpx.Client(
                base_url=self._base_url,
                headers={
                    **common_headers,
                    "Authorization": f"Bearer {oauth_config.access_token}",
                },
                timeout=timeout,
            )
        elif config is not None:
            self._auth_mode = "api_key"
            self._oauth_config = None
            self._base_url = config.base_url.rstrip("/")
            self._http = httpx.Client(
                base_url=self._base_url,
                headers={
                    **common_headers,
                    "Authorization": f"Bearer {config.api_key}",
                },
                timeout=timeout,
            )
        else:
            raise ValueError("Either config or oauth_config must be provided")

        self.config = config
        self._session_id: str | None = None
        self._timeout = timeout

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── URL helpers ──────────────────────────────────────────────

    @property
    def _mcp_url(self) -> str:
        if self._auth_mode == "oauth":
            return "/mcp"
        # API key mode — needs tool_pack_id and registered_user_id
        if self.config is None:
            raise MergeClientError("API key config is required for this endpoint")
        tp = self.config.tool_pack_id
        ru = self.config.registered_user_id
        return f"/api/v1/tool-packs/{tp}/registered-users/{ru}/mcp"

    # ── MCP JSON-RPC helpers ─────────────────────────────────────

    def _mcp_request(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC 2.0 request to the MCP endpoint."""
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
        }
        if params is not None:
            body["params"] = params

        headers = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        resp = self._http.post(self._mcp_url, json=body, headers=headers)

        # Capture session ID from response
        if "Mcp-Session-Id" in resp.headers:
            self._session_id = resp.headers["Mcp-Session-Id"]

        # Handle 401 — try token refresh for OAuth mode
        if resp.status_code == 401 and self._auth_mode == "oauth":
            if self._try_refresh_token():
                # Reset session — new token may need new session
                self._session_id = None
                self._ensure_initialized()
                # Rebuild headers with new session
                retry_headers = {}
                if self._session_id:
                    retry_headers["Mcp-Session-Id"] = self._session_id
                resp = self._http.post(self._mcp_url, json=body, headers=retry_headers)
            else:
                raise MergeClientError(
                    "Session expired. Run `merge login` to re-authenticate.",
                    status_code=401,
                )

        if resp.status_code != 200:
            raise MergeClientError(
                f"MCP request failed: {resp.status_code} {resp.text}",
                status_code=resp.status_code,
            )

        data = resp.json()

        # Check for JSON-RPC error
        if "error" in data:
            err = data["error"]
            raise MergeClientError(
                f"JSON-RPC error ({err.get('code')}): {err.get('message')}",
            )

        return data

    def _try_refresh_token(self) -> bool:
        """Attempt to refresh the OAuth access token. Returns True if successful."""
        if self._oauth_config is None or not self._oauth_config.refresh_token:
            return False

        try:
            resp = httpx.post(
                f"{self._base_url}/o/token/",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._oauth_config.refresh_token,
                    "client_id": self._oauth_config.client_id,
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                return False

            data = resp.json()
            new_access = data["access_token"]
            new_refresh = data.get("refresh_token", self._oauth_config.refresh_token)

            # Update in-memory config
            self._oauth_config.access_token = new_access
            self._oauth_config.refresh_token = new_refresh

            # Update HTTP client headers
            self._http.headers["Authorization"] = f"Bearer {new_access}"

            # Persist to disk
            save_oauth_config(
                access_token=new_access,
                refresh_token=new_refresh,
                client_id=self._oauth_config.client_id,
                base_url=self._oauth_config.base_url,
            )

            return True
        except Exception:
            return False

    def _ensure_initialized(self) -> None:
        """Initialize MCP session if not already done."""
        if self._session_id is None:
            self._session_id = str(uuid.uuid4())
            self._mcp_request("initialize", {"protocolVersion": "2024-11-05"})

    # ── Public methods ───────────────────────────────────────────

    def search_tools(
        self,
        intent: str,
        *,
        connector_slugs: list[str] | None = None,
        max_results: int = 10,
    ) -> dict:
        """Search for tools by natural language intent.

        Uses MCP tools/call with the built-in search_tools tool. Works in
        both OAuth and API key mode.

        Returns {"tools": [...], "total_results": N}.
        """
        self._ensure_initialized()
        arguments: dict[str, Any] = {"intent": intent, "max_results": max_results}
        if connector_slugs is not None:
            arguments["connector_slugs"] = connector_slugs

        raw = self.call_tool("search_tools", arguments)
        parsed = self.parse_tool_result(raw)

        if parsed.get("status") != "success":
            raise MergeClientError(
                parsed.get("message", "Search failed"),
            )

        # The MCP tool returns a ToolSearchResponse with tools, requestable_tools,
        # request_access_tool_name, and message.
        results = parsed.get("result", {})
        if isinstance(results, list):
            # Legacy format fallback
            results = {"tools": results}
        if not isinstance(results, dict):
            results = {"tools": []}

        for r in results.get("tools", []):
            r.pop("relevance_score", None)
            r.pop("reasoning", None)
        for r in results.get("requestable_tools", []):
            r.pop("relevance_score", None)
            r.pop("reasoning", None)

        tools = results.get("tools", [])
        requestable_tools = results.get("requestable_tools", [])
        return {
            "tools": tools,
            "total_results": len(tools),
            "requestable_tools": requestable_tools,
            "request_access_tool_name": results.get("request_access_tool_name"),
            "message": results.get("message"),
        }

    def list_tools(self) -> list[dict]:
        """List all available tools via MCP tools/list."""
        self._ensure_initialized()
        data = self._mcp_request("tools/list")
        # `or {}` guards a valid JSON-RPC `{"result": null}` (key present, so a
        # .get default wouldn't fire) that would otherwise crash on .get("tools").
        return (data.get("result") or {}).get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool via MCP tools/call. Returns the full JSON-RPC result."""
        self._ensure_initialized()
        data = self._mcp_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        # `or {}` (not a .get default): a valid JSON-RPC `{"result": null}` sets the
        # key, so the default wouldn't fire and parse_tool_result would get None.
        return data.get("result") or {}

    def list_tool_call_logs(self, params: dict | None = None) -> list[dict]:
        """Fetch tool-call logs (GET /api/v1/logs/tool-calls/), following the cursor.

        Results are oldest-first and cover the last 30 days; Enterprise plans only. Paging
        stops when `has_more` is false, so narrow with `created_after` to avoid a full scan.
        """
        query = {k: v for k, v in (params or {}).items() if v is not None}
        # Largest page the API allows; the default of 100 means ten times the round trips.
        query.setdefault("page_size", 1000)
        records: list[dict] = []
        seen_cursors: set[str] = set()
        refreshed = False
        while True:
            resp = self._http.get("/api/v1/logs/tool-calls/", params=query)
            # Same recovery as _mcp_request: an expired OAuth token is refreshed and the
            # request retried once. _try_refresh_token updates the client's Authorization
            # header, so the retry goes out with the new token.
            if resp.status_code == 401 and self._auth_mode == "oauth" and not refreshed:
                refreshed = True
                if not self._try_refresh_token():
                    raise MergeClientError(
                        "Session expired. Run `merge login` to re-authenticate.",
                        status_code=401,
                    )
                continue
            if resp.status_code != 200:
                raise MergeClientError(
                    f"Logs request failed: {resp.status_code} {resp.text}",
                    status_code=resp.status_code,
                )
            data = resp.json()
            if isinstance(data, list):
                return records + data
            records.extend(data.get("results") or [])
            cursor = data.get("next_cursor")
            # A repeated cursor means the server is not advancing; stop rather than loop forever.
            if not data.get("has_more") or not cursor or cursor in seen_cursors:
                return records
            seen_cursors.add(cursor)
            query["cursor"] = cursor

    def get_tool_schema(self, tool_name: str) -> dict | None:
        """Get the input schema for a single tool (filters from tools/list)."""
        tools = self.list_tools()
        for tool in tools:
            if tool.get("name") == tool_name:
                return tool
        return None

    def parse_tool_result(self, result: dict) -> dict:
        """Parse MCP tool/call result into a structured response.

        Handles success, reauth_required, billing_limit_reached, and generic errors.
        """
        is_error = result.get("isError", False)
        content_list = result.get("content", [])
        raw_text = ""
        for item in content_list:
            if item.get("type") == "text":
                raw_text = item.get("text", "")
                break

        # Try to parse as JSON
        try:
            parsed = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw_text}

        if not is_error:
            return {
                "result": parsed if parsed else raw_text,
                "status": "success",
                "hint": "Tool executed successfully.",
            }

        # Handle known error types
        error_type = parsed.get("error", "execution_error")
        message = parsed.get("message", raw_text or "Tool execution failed.")

        if error_type == "reauth_required":
            return {
                "result": None,
                "status": "error",
                "error_type": "reauth_required",
                "message": message,
                "hint": "Authentication required. The user needs to re-connect their account.",
            }
        elif error_type == "billing_limit_reached":
            billing_url = parsed.get("billing_page_url", "")
            hint = "Billing limit reached. Upgrade the account to continue."
            if billing_url:
                hint += f" Billing page: {billing_url}"
            return {
                "result": None,
                "status": "error",
                "error_type": "billing_limit_reached",
                "message": message,
                "hint": hint,
            }
        else:
            return {
                "result": None,
                "status": "error",
                "error_type": error_type,
                "message": message,
                "hint": f"Tool execution failed: {message}",
            }
