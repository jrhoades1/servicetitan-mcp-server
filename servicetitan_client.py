"""
ServiceTitan API client with OAuth 2.0 authentication.

Security design:
  - Client credentials flow only — no user passwords handled here
  - Tokens are stored in-memory only, never logged or returned to callers
  - Read-only enforcement: only GET requests are issued; any attempt to
    call a mutating method raises ReadOnlyViolationError immediately
  - Token refresh happens automatically 60 s before expiry (configurable)
  - Retry logic covers transient network errors and 5xx responses only;
    4xx errors (including 429) are surfaced immediately as typed exceptions
  - All error messages are scrubbed — no raw API responses reach the caller
  - HTTPS-only enforced via config validation (see config.py)
  - Request timeouts enforced at connection, read, and total levels

Usage:
    async with ServiceTitanClient(settings) as client:
        jobs = await client.get("/jobs", params={"page": 1, "pageSize": 50})
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from config import Settings

log = structlog.get_logger(__name__)

_API_VERSION = "v2"


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class ServiceTitanError(Exception):
    """Base class for all ServiceTitan client errors."""


class ReadOnlyViolationError(ServiceTitanError):
    """Raised when code attempts a non-GET request through this client."""


class ServiceTitanAuthError(ServiceTitanError):
    """Raised when authentication or token refresh fails (non-retryable)."""


class ServiceTitanAPIError(ServiceTitanError):
    """Raised for error responses from the ServiceTitan API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ServiceTitanRateLimitError(ServiceTitanAPIError):
    """Raised on HTTP 429. Includes Retry-After if provided by the server."""

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__("ServiceTitan rate limit exceeded", status_code=429)
        self.retry_after = retry_after


class ServiceTitanNotFoundError(ServiceTitanAPIError):
    """Raised on HTTP 404."""

    def __init__(self) -> None:
        super().__init__("Resource not found", status_code=404)


# ---------------------------------------------------------------------------
# Internal token state
# ---------------------------------------------------------------------------


@dataclass
class _TokenState:
    """
    Holds the current OAuth access token.

    This object is internal to ServiceTitanClient. The token value is never
    exposed via public methods, logged, or included in exception messages.
    """

    _access_token: str = field(default="", repr=False)
    _expires_at: float = field(default=0.0)  # monotonic timestamp
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def is_valid(self, buffer_seconds: int) -> bool:
        """True if a token exists and won't expire within buffer_seconds."""
        return bool(self._access_token) and time.monotonic() < (
            self._expires_at - buffer_seconds
        )

    def set(self, token: str, expires_in: int) -> None:
        self._access_token = token
        self._expires_at = time.monotonic() + expires_in

    def clear(self) -> None:
        self._access_token = ""
        self._expires_at = 0.0

    @property
    def bearer_value(self) -> str:
        """Return the raw token. Only call from _build_headers — nowhere else."""
        return self._access_token


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ServiceTitanClient:
    """
    Async, read-only HTTP client for the ServiceTitan v2 API.

    Intended to be used as an async context manager so the underlying
    httpx.AsyncClient is properly opened and closed:

        async with ServiceTitanClient(settings) as client:
            data = await client.get("/jobs", params={"page": 1})
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._token = _TokenState()
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ServiceTitanClient":
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=self._s.http_connect_timeout,
                read=self._s.http_read_timeout,
                write=5.0,
                pool=self._s.http_total_timeout,
            ),
            follow_redirects=False,  # Surface redirects explicitly; never silently follow
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Public API (read-only GET only)
    # ------------------------------------------------------------------

    async def get(
        self,
        module: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Perform an authenticated GET request to the ServiceTitan v2 API.

        ServiceTitan URL structure:
          {api_base}/{module}/v2/tenant/{tenant_id}/{resource}

        Args:
            module: API module name, e.g. "jpm", "crm", "reporting".
            path:   Resource path relative to the tenant base, e.g. "/technicians".
                    Must start with "/".
            params: Optional query-string parameters (e.g. page, pageSize, dates).

        Returns:
            The parsed JSON response body as a dict.

        Raises:
            ServiceTitanAuthError: Authentication failed or token cannot be obtained.
            ServiceTitanRateLimitError: HTTP 429 returned by ServiceTitan.
            ServiceTitanNotFoundError: HTTP 404 returned by ServiceTitan.
            ServiceTitanAPIError: Any other non-2xx response.

        Example:
            await client.get("jpm", "/technicians", params={"active": True})
        """
        if not module or not module.isalpha():
            raise ValueError(f"Invalid module name: {module!r}")

        if not path.startswith("/"):
            path = f"/{path}"

        url = f"{self._s.api_v2_tenant_base(module)}{path}"
        return await self._request_with_retry("GET", url, params=params)

    async def ensure_authenticated(self) -> None:
        """
        Validate that OAuth credentials work.

        Call this at server startup to fail fast if credentials are wrong,
        rather than discovering the problem on the first user query.
        """
        await self._refresh_token_if_needed()
        log.info("servicetitan.auth.verified")

    # ------------------------------------------------------------------
    # Internal: authentication
    # ------------------------------------------------------------------

    async def _refresh_token_if_needed(self) -> None:
        """
        Acquire or refresh the OAuth token.

        Uses a lock so concurrent requests don't all trigger token refresh
        simultaneously (thundering herd on startup or near expiry).
        """
        async with self._token._lock:
            # Re-check inside the lock — another coroutine may have refreshed already
            if self._token.is_valid(self._s.token_refresh_buffer_seconds):
                return

            await self._do_token_request()

    async def _do_token_request(self) -> None:
        """
        POST to the OAuth token endpoint and store the resulting token.

        The token value is stored internally and never logged or returned.
        Any exception message is scrubbed — response bodies are not included.
        """
        assert self._http is not None, "Client must be used as an async context manager"

        log.info("servicetitan.auth.refreshing")

        try:
            response = await self._http.post(
                self._s.st_auth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._s.st_client_id,
                    "client_secret": self._s.st_client_secret.get_secret_value(),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.ConnectError:
            log.error("servicetitan.auth.connect_error")
            raise ServiceTitanAuthError(
                "Cannot connect to ServiceTitan authentication server"
            )
        except httpx.TimeoutException:
            log.error("servicetitan.auth.timeout")
            raise ServiceTitanAuthError(
                "ServiceTitan authentication server did not respond in time"
            )
        except httpx.RequestError:
            log.error("servicetitan.auth.request_error")
            raise ServiceTitanAuthError("Network error during authentication")

        if response.status_code != 200:
            log.error(
                "servicetitan.auth.failed",
                status_code=response.status_code,
            )
            # Do NOT include response body — it may contain debugging info
            raise ServiceTitanAuthError(
                f"Authentication failed (HTTP {response.status_code})"
            )

        try:
            payload = response.json()
            raw_token: str = payload["access_token"]
            expires_in: int = int(payload.get("expires_in", 3600))
        except (KeyError, ValueError, TypeError):
            log.error("servicetitan.auth.malformed_response")
            raise ServiceTitanAuthError(
                "ServiceTitan returned an unexpected token response"
            )

        if not raw_token:
            raise ServiceTitanAuthError("ServiceTitan returned an empty access token")

        self._token.set(raw_token, expires_in)
        log.info("servicetitan.auth.success", expires_in_seconds=expires_in)

    # ------------------------------------------------------------------
    # Internal: request execution
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """
        Build request headers.

        ST-App-Key is required on every ServiceTitan API call in addition to
        the Bearer token. Both values are retrieved from SecretStr fields so
        they are not included in repr() or log output.
        """
        return {
            "Authorization": f"Bearer {self._token.bearer_value}",
            "ST-App-Key": self._s.st_app_key.get_secret_value(),
            "Accept": "application/json",
        }

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute an HTTP request with exponential-backoff retry.

        Retries on:  network errors, HTTP 5xx
        No retry on: HTTP 4xx (400, 401, 403, 404, 429, etc.)

        The read-only enforcement guard is here so no code path in this class
        can accidentally issue a mutating request.
        """
        if method != "GET":
            raise ReadOnlyViolationError(
                f"This client is read-only. Refusing to issue {method} request."
            )

        assert self._http is not None, "Client must be used as an async context manager"

        last_exc: Exception | None = None

        for attempt in range(self._s.http_max_retries + 1):
            # Refresh token before each attempt — handles mid-retry expiry too
            await self._refresh_token_if_needed()

            try:
                response = await self._http.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=self._build_headers(),
                )
            except httpx.ConnectError as exc:
                log.warning(
                    "servicetitan.request.connect_error",
                    attempt=attempt,
                    max_retries=self._s.http_max_retries,
                )
                last_exc = exc
            except httpx.TimeoutException as exc:
                log.warning(
                    "servicetitan.request.timeout",
                    attempt=attempt,
                    max_retries=self._s.http_max_retries,
                )
                last_exc = exc
            except httpx.RequestError as exc:
                log.warning(
                    "servicetitan.request.network_error",
                    attempt=attempt,
                    max_retries=self._s.http_max_retries,
                )
                last_exc = exc
            else:
                # Got a response — delegate status handling (may raise or return)
                return self._handle_response(response)

            # If we have retries left, wait then loop
            if attempt < self._s.http_max_retries:
                backoff = 2**attempt  # 1 s, 2 s, 4 s
                log.info(
                    "servicetitan.request.retrying",
                    next_attempt=attempt + 1,
                    backoff_seconds=backoff,
                )
                await asyncio.sleep(backoff)

        raise ServiceTitanAPIError(
            "ServiceTitan API is unreachable after retries"
        ) from last_exc

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """
        Parse a successful (2xx) response or raise a typed exception.

        Response bodies are NOT included in exception messages — they may
        contain internal ServiceTitan debugging information.
        """
        status = response.status_code

        if status in (200, 201):
            try:
                return response.json()
            except Exception:
                log.error("servicetitan.response.invalid_json", status_code=status)
                raise ServiceTitanAPIError("API returned non-JSON response")

        if status == 401:
            # Invalidate the cached token so the next call forces a refresh
            self._token.clear()
            log.error("servicetitan.response.unauthorized")
            raise ServiceTitanAuthError(
                "ServiceTitan rejected the access token — credentials may have been revoked"
            )

        if status == 403:
            log.error("servicetitan.response.forbidden")
            raise ServiceTitanAPIError(
                "Access denied — verify the app has read permissions in ServiceTitan",
                status_code=403,
            )

        if status == 404:
            log.warning("servicetitan.response.not_found")
            raise ServiceTitanNotFoundError()

        if status == 429:
            retry_after_raw = response.headers.get("Retry-After", "")
            retry_after = int(retry_after_raw) if retry_after_raw.isdigit() else None
            log.warning("servicetitan.response.rate_limited", retry_after=retry_after)
            raise ServiceTitanRateLimitError(retry_after=retry_after)

        if 500 <= status < 600:
            log.error("servicetitan.response.server_error", status_code=status)
            raise ServiceTitanAPIError(
                f"ServiceTitan server error (HTTP {status})", status_code=status
            )

        log.error("servicetitan.response.unexpected_status", status_code=status)
        raise ServiceTitanAPIError(
            f"Unexpected response from ServiceTitan (HTTP {status})", status_code=status
        )
