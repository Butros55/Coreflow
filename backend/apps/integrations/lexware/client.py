"""Lexware Office API client.

Implements the contract verified in docs/integrations/lexware.md:
  * Bearer auth, base URL from settings.
  * Global 2 req/s limiter (shared bucket), retry/backoff, no Retry-After.
  * Three error body shapes normalised to one ProviderHTTPError.
  * Validation failures are 406, not 400/422.
  * Invoice POST is NON-idempotent (a 504 may mean it succeeded).
  * PDF download via GET /v1/invoices/{id}/file (not the deprecated flow).
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

logger = get_logger("integrations.lexware")

# One shared limiter per process: Lexware's 2 req/s cap is global across every
# endpoint and every worker thread.
_LEXWARE_LIMITER = TokenBucketLimiter(rate_per_second=2.0, burst=1)


class LexwareError(ProviderHTTPError):
    """Lexware-specific error, carrying the traceId for support when present."""

    def __init__(self, *args: Any, trace_id: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.trace_id = trace_id


class LexwareClient(BaseHTTPClient):
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key if api_key is not None else settings.LEXWARE_API_KEY
        config = HTTPClientConfig(
            base_url=base_url or settings.LEXWARE_API_BASE_URL,
            timeout=settings.LEXWARE_TIMEOUT_SECONDS,
            max_retries=settings.LEXWARE_MAX_RETRIES,
            rate_per_second=2.0,
            default_headers={"Accept": "application/json"},
        )
        super().__init__(config, limiter=_LEXWARE_LIMITER)

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def parse_error(self, response: httpx.Response) -> LexwareError:
        status = response.status_code
        retryable = status in self.RETRYABLE_STATUSES
        try:
            body = response.json()
        except ValueError:
            body = {}

        # Shape 1: legacy IssueList (contacts, files, vouchers).
        if isinstance(body, dict) and "IssueList" in body:
            issues = body.get("IssueList") or []
            first = issues[0] if issues else {}
            message = first.get("i18nKey", "validation_failure")
            return LexwareError(
                f"Lexware-Validierungsfehler: {message}",
                status_code=status,
                code=str(message),
                payload=body,
                retryable=retryable,
            )
        # Shape 2: regular (invoices, profile, voucherlist, ...).
        if isinstance(body, dict) and "status" in body and "message" in body:
            return LexwareError(
                str(body.get("message", "Fehler")),
                status_code=status,
                code=str(body.get("error", "error")).lower().replace(" ", "_"),
                payload=body,
                trace_id=body.get("traceId"),
                retryable=retryable,
            )
        # Shape 3: bare {"message": ...} (auth/connection).
        message = body.get("message") if isinstance(body, dict) else None
        code = {
            401: "unauthorized",
            403: "forbidden",
            402: "payment_required",
            406: "validation_failed",
            409: "conflict",
            429: "rate_limited",
        }.get(status, f"http_{status}")
        return LexwareError(
            message or f"Lexware-Fehler (HTTP {status})",
            status_code=status,
            code=code,
            payload=body,
            retryable=retryable,
        )

    # -- resources ---------------------------------------------------------

    def get_profile(self) -> dict[str, Any]:
        """Connection test + org/tax metadata. See lexware.md §4.1."""
        return cast("dict[str, Any]", self.get("/v1/profile").json())

    def list_contacts(self, page: int = 0, size: int = 100, **filters: Any) -> dict[str, Any]:
        params = {"page": page, "size": min(size, 250), **filters}
        return cast("dict[str, Any]", self.get("/v1/contacts", params=params).json())

    def get_contact(self, contact_id: str) -> dict[str, Any]:
        return cast("dict[str, Any]", self.get(f"/v1/contacts/{contact_id}").json())

    def create_contact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return cast("dict[str, Any]", self.post("/v1/contacts", json=payload).json())

    def create_invoice(self, payload: dict[str, Any], *, finalize: bool = False) -> dict[str, Any]:
        """Create an invoice. NON-idempotent — never auto-retried (see §6.4).

        ``finalize=True`` issues a legally binding invoice immediately; there is
        no draft→open transition afterwards. Off by default.
        """
        params = {"finalize": "true"} if finalize else None
        return cast(
            "dict[str, Any]",
            self.post("/v1/invoices", params=params, json=payload, idempotent=False).json(),
        )

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        return cast("dict[str, Any]", self.get(f"/v1/invoices/{invoice_id}").json())

    def download_invoice_file(self, invoice_id: str, accept: str = "application/pdf") -> bytes:
        """PDF/e-invoice bytes via the current endpoint (not documentFileId)."""
        response = self.get(f"/v1/invoices/{invoice_id}/file", headers={"Accept": accept})
        return response.content

    def get_payments(self, voucher_id: str) -> dict[str, Any] | None:
        """Payment info for a voucher. 406 = "no payment info yet", not an error."""
        try:
            return cast("dict[str, Any]", self.get(f"/v1/payments/{voucher_id}").json())
        except LexwareError as exc:
            if exc.status_code == 406:
                return None
            raise

    def voucherlist(
        self, voucher_type: str, voucher_status: str, page: int = 0, **filters: Any
    ) -> dict[str, Any]:
        """Both voucher_type and voucher_status are mandatory (§4.7)."""
        params = {
            "voucherType": voucher_type,
            "voucherStatus": voucher_status,
            "page": page,
            "size": 250,
            **filters,
        }
        return cast("dict[str, Any]", self.get("/v1/voucherlist", params=params).json())

    def create_event_subscription(self, event_type: str, callback_url: str) -> dict[str, Any]:
        response = self.post(
            "/v1/event-subscriptions",
            json={"eventType": event_type, "callbackUrl": callback_url},
        )
        return cast("dict[str, Any]", response.json())

    def list_event_subscriptions(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self.get("/v1/event-subscriptions").json())

    def delete_event_subscription(self, subscription_id: str) -> None:
        self.delete(f"/v1/event-subscriptions/{subscription_id}")


def is_lexware_enabled() -> bool:
    return bool(settings.LEXWARE_ENABLED and settings.LEXWARE_API_KEY)
