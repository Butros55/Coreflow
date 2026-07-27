"""Provider port and shared HTTP plumbing.

Both providers are thin HTTP APIs with quirks a hand-written client documents
better than an SDK hides. The shared pieces — a token-bucket limiter, retry with
backoff, error normalisation — live here; each provider subclasses and fills in
auth, base URL and error parsing.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Self

import httpx

from apps.core.logging import get_logger

logger = get_logger("integrations.http")


class ProviderHTTPError(Exception):
    """Normalised provider error. Carries the status and a machine code."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str = "provider_error",
        payload: Any = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.payload = payload
        self.retryable = retryable


class TokenBucketLimiter:
    """Process-wide rate limiter.

    Lexware's 2 req/s ceiling is **global across all endpoints**, so a single
    shared bucket — not one per resource — is what keeps us under it. Thread-safe
    because a Celery worker runs several tasks concurrently.
    """

    def __init__(self, rate_per_second: float, burst: int = 1) -> None:
        self._rate = rate_per_second
        self._capacity = max(burst, 1)
        self._tokens = float(self._capacity)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated
                self._updated = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                # Not enough tokens: sleep the shortfall, holding the lock so the
                # ordering across threads stays fair.
                needed = (1 - self._tokens) / self._rate
                time.sleep(needed)


@dataclass
class HTTPClientConfig:
    base_url: str
    timeout: float = 30.0
    max_retries: int = 4
    rate_per_second: float = 2.0
    backoff_base: float = 0.5
    backoff_cap: float = 30.0
    default_headers: dict[str, str] = field(default_factory=dict)


class BaseHTTPClient:
    """HTTP client with a shared limiter and retry/backoff.

    Subclasses override :meth:`parse_error` to turn a provider's error body into
    a :class:`ProviderHTTPError` with a stable code.
    """

    # Overridden per provider. 5xx and 429 are retryable by default; 500 is here
    # because Lexware documents "500 = server error OR rate limit exceeded".
    RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def __init__(self, config: HTTPClientConfig, limiter: TokenBucketLimiter | None = None) -> None:
        self.config = config
        self._limiter = limiter or TokenBucketLimiter(config.rate_per_second)
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout,
            headers=config.default_headers,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- to override -------------------------------------------------------

    def parse_error(self, response: httpx.Response) -> ProviderHTTPError:
        raise NotImplementedError

    def auth_headers(self) -> dict[str, str]:
        return {}

    # -- request -----------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        idempotent: bool = True,
    ) -> httpx.Response:
        """Issue a request, honouring the limiter and retrying transient failures.

        ``idempotent=False`` disables retries — a non-idempotent POST (e.g.
        creating an invoice) must never be blindly retried, because a 504 may
        mean it already succeeded (see lexware.md §6.4).
        """
        merged_headers = {**self.auth_headers(), **(headers or {})}
        attempt = 0
        last_error: ProviderHTTPError | None = None

        while True:
            attempt += 1
            self._limiter.acquire()
            try:
                response = self._client.request(
                    method, path, params=params, json=json, headers=merged_headers
                )
            except httpx.TimeoutException as exc:
                last_error = ProviderHTTPError(
                    "Zeitüberschreitung bei der Anfrage.",
                    code="timeout",
                    retryable=idempotent,
                )
                if not idempotent or attempt > self.config.max_retries:
                    raise last_error from exc
                self._sleep_backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                raise ProviderHTTPError(
                    f"Verbindungsfehler: {type(exc).__name__}", code="connection_error"
                ) from exc

            if response.is_success:
                return response

            error = self.parse_error(response)
            should_retry = (
                idempotent
                and error.retryable
                and response.status_code in self.RETRYABLE_STATUSES
                and attempt <= self.config.max_retries
            )
            # Log without the body — it can carry customer data; scrubbing
            # covers headers but the body is not passed to the logger at all.
            logger.warning(
                "provider_request_failed",
                method=method,
                path=path,
                status=response.status_code,
                code=error.code,
                attempt=attempt,
                will_retry=should_retry,
            )
            if not should_retry:
                raise error
            last_error = error
            self._sleep_backoff(attempt, response)

    def _sleep_backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        # Honour Retry-After when present (Clockify sends it on 429), else
        # exponential backoff with a cap (Lexware documents no Retry-After).
        retry_after = None
        if response is not None:
            header = response.headers.get("Retry-After")
            if header and header.isdigit():
                retry_after = float(header)
        delay = (
            retry_after
            if retry_after is not None
            else min(self.config.backoff_base * (2 ** (attempt - 1)), self.config.backoff_cap)
        )
        time.sleep(delay)

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)
