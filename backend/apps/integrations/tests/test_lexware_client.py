"""Lexware client tests — all HTTP is mocked (no sandbox exists)."""

from __future__ import annotations

import httpx
import pytest
import respx

from apps.integrations.base import ProviderHTTPError, TokenBucketLimiter
from apps.integrations.lexware.client import LexwareClient

pytestmark = pytest.mark.django_db

BASE = "https://api.lexware.io"


@pytest.fixture
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the rate limiter so tests don't actually sleep."""
    monkeypatch.setattr(TokenBucketLimiter, "acquire", lambda self: None)


def make_client(max_retries: int = 3) -> LexwareClient:
    # Test settings pin LEXWARE_MAX_RETRIES=0 so failure-path tests stay fast;
    # override per-client where a test exercises retry behaviour.
    client = LexwareClient(api_key="test-key", base_url=BASE)
    client.config.max_retries = max_retries
    return client


@respx.mock
def test_get_profile_sends_bearer_auth(fast_limiter: None) -> None:
    route = respx.get(f"{BASE}/v1/profile").mock(
        return_value=httpx.Response(
            200,
            json={
                "organizationId": "org-1",
                "companyName": "Test GmbH",
                "taxType": "net",
                "smallBusiness": False,
            },
        )
    )
    with make_client() as client:
        profile = client.get_profile()

    assert profile["organizationId"] == "org-1"
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-key"


@respx.mock
def test_validation_error_406_regular_shape(fast_limiter: None) -> None:
    respx.post(f"{BASE}/v1/invoices").mock(
        return_value=httpx.Response(
            406,
            json={
                "status": 406,
                "error": "Not Acceptable",
                "path": "/v1/invoices",
                "traceId": "abc123",
                "message": "Validation failed",
                "details": [{"violation": "NOTNULL", "field": "lineItems"}],
            },
        )
    )
    with make_client() as client, pytest.raises(ProviderHTTPError) as exc_info:
        client.create_invoice({}, finalize=False)

    error = exc_info.value
    assert error.status_code == 406
    assert error.code == "not_acceptable"
    assert getattr(error, "trace_id", None) == "abc123"


@respx.mock
def test_legacy_issuelist_error_shape(fast_limiter: None) -> None:
    respx.post(f"{BASE}/v1/contacts").mock(
        return_value=httpx.Response(
            406,
            json={
                "IssueList": [
                    {
                        "i18nKey": "missing_entity",
                        "source": "company.name",
                        "type": "validation_failure",
                    }
                ]
            },
        )
    )
    with make_client() as client, pytest.raises(ProviderHTTPError) as exc_info:
        client.create_contact({})
    assert exc_info.value.code == "missing_entity"


@respx.mock
def test_bare_message_auth_error(fast_limiter: None) -> None:
    respx.get(f"{BASE}/v1/profile").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )
    with make_client() as client, pytest.raises(ProviderHTTPError) as exc_info:
        client.get_profile()
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "unauthorized"


@respx.mock
def test_retries_on_500_then_succeeds(fast_limiter: None) -> None:
    # 500 can mean "rate limited" at Lexware, so it is retryable.
    route = respx.get(f"{BASE}/v1/profile").mock(
        side_effect=[
            httpx.Response(500, json={"message": "Internal server error or rate limit exceeded"}),
            httpx.Response(200, json={"organizationId": "org-1"}),
        ]
    )
    with make_client() as client:
        profile = client.get_profile()
    assert profile["organizationId"] == "org-1"
    assert route.call_count == 2


@respx.mock
def test_invoice_post_is_not_retried_on_timeout(fast_limiter: None) -> None:
    """A 504 may mean the invoice WAS created — the POST must not be retried."""
    route = respx.post(f"{BASE}/v1/invoices").mock(side_effect=httpx.TimeoutException("timeout"))
    with make_client() as client, pytest.raises(ProviderHTTPError) as exc_info:
        client.create_invoice({"foo": "bar"}, finalize=False)
    assert exc_info.value.code == "timeout"
    # Exactly one attempt — no retry.
    assert route.call_count == 1


@respx.mock
def test_get_payments_treats_406_as_no_info(fast_limiter: None) -> None:
    respx.get(f"{BASE}/v1/payments/inv-1").mock(
        return_value=httpx.Response(406, json={"status": 406, "message": "draft"})
    )
    with make_client() as client:
        result = client.get_payments("inv-1")
    assert result is None  # not an error


@respx.mock
def test_download_invoice_file_returns_bytes(fast_limiter: None) -> None:
    respx.get(f"{BASE}/v1/invoices/inv-1/file").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.7 fake")
    )
    with make_client() as client:
        content = client.download_invoice_file("inv-1")
    assert content.startswith(b"%PDF")


class TestTokenBucketLimiter:
    def test_allows_burst_then_throttles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr(
            "apps.integrations.base.time.sleep", lambda seconds: slept.append(seconds)
        )
        # 2 tokens/sec, burst 2: first two acquire free, third must wait.
        limiter = TokenBucketLimiter(rate_per_second=2.0, burst=2)
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()
        assert len(slept) >= 1
