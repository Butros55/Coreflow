"""Clockodo API client.

Implements the verified contract in docs/integrations/clockodo.md:
  * Custom-header auth (X-ClockodoApiUser/Key + the mandatory
    X-Clockodo-External-Application "name;email").
  * v3/v4 resource paths (customers v3, projects v4, entries v2).
  * Two error shapes: {"errors": [...]} for most, {"error": {...}} for entries.

This phase wires the connection test and customer/project reads; full
bidirectional entry sync is Phase 4 and is intentionally not implemented here.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
from django.conf import settings

from apps.core.logging import get_logger
from apps.integrations.base import (
    BaseHTTPClient,
    HTTPClientConfig,
    ProviderHTTPError,
    TokenBucketLimiter,
)

logger = get_logger("integrations.clockodo")

# Clockodo's global limit is generous (900/min); a modest shared bucket keeps us
# well clear without serialising as aggressively as Lexware.
_CLOCKODO_LIMITER = TokenBucketLimiter(rate_per_second=8.0, burst=4)


class ClockodoError(ProviderHTTPError):
    """Clockodo error. Matched on `type`, never the localized message."""


class ClockodoClient(BaseHTTPClient):
    def __init__(
        self,
        api_user: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._api_user = api_user if api_user is not None else settings.CLOCKODO_API_USER
        self._api_key = api_key if api_key is not None else settings.CLOCKODO_API_KEY
        external_app = (
            f"{settings.CLOCKODO_EXTERNAL_APP_NAME};{settings.CLOCKODO_EXTERNAL_APP_EMAIL}"
        )
        config = HTTPClientConfig(
            base_url=base_url or settings.CLOCKODO_API_BASE_URL,
            timeout=settings.CLOCKODO_TIMEOUT_SECONDS,
            max_retries=settings.CLOCKODO_MAX_RETRIES,
            rate_per_second=8.0,
            default_headers={
                "Accept": "application/json",
                # Mandatory on EVERY request — a blank email makes all calls fail.
                "X-Clockodo-External-Application": external_app,
            },
        )
        super().__init__(config, limiter=_CLOCKODO_LIMITER)

    def auth_headers(self) -> dict[str, str]:
        return {
            "X-ClockodoApiUser": self._api_user,
            "X-ClockodoApiKey": self._api_key,
        }

    def parse_error(self, response: httpx.Response) -> ClockodoError:
        status = response.status_code
        retryable = status in self.RETRYABLE_STATUSES
        try:
            body = response.json()
        except ValueError:
            body = {}

        error_type = "error"
        message = f"Clockodo-Fehler (HTTP {status})"
        # /v2/entries uses {"error": {code, message}}; everything else
        # {"errors": [{type, message}]}.
        if isinstance(body, dict):
            if isinstance(body.get("error"), dict):
                message = str(body["error"].get("message", message))
                error_type = str(body["error"].get("code", status))
            elif isinstance(body.get("errors"), list) and body["errors"]:
                first = body["errors"][0]
                message = str(first.get("message", message))
                error_type = str(first.get("type", "error"))
        code = {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}.get(
            status, str(error_type)
        )
        return ClockodoError(
            message, status_code=status, code=code, payload=body, retryable=retryable
        )

    # -- resources ---------------------------------------------------------

    def get_users_me(self) -> dict[str, Any]:
        """Connection test: /v4/users/me returns the authenticated user."""
        return cast("dict[str, Any]", self.get("/v4/users/me").json())

    def list_customers(self, page: int = 1) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.get("/v3/customers", params={"page": page, "items_per_page": 100}).json(),
        )

    def list_projects(self, page: int = 1) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.get("/v4/projects", params={"page": page, "items_per_page": 100}).json(),
        )

    def list_services(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self.get("/v4/services").json())


def is_clockodo_enabled() -> bool:
    return bool(
        settings.CLOCKODO_ENABLED and settings.CLOCKODO_API_USER and settings.CLOCKODO_API_KEY
    )
