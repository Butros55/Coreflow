"""Integration centre: status, connection test (mocked), conflict resolution."""

from __future__ import annotations

import httpx
import pytest
import respx
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.integrations.base import TokenBucketLimiter
from apps.integrations.models import (
    ConflictResolutionStatus,
    Provider,
    ProviderProfile,
    SyncConflict,
)

pytestmark = pytest.mark.django_db

LEXWARE_BASE = "https://api.lexware.io"


@pytest.fixture
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TokenBucketLimiter, "acquire", lambda self: None)


class TestStatus:
    def test_status_reports_disabled_by_default(self, auth_client: APIClient) -> None:
        response = auth_client.get(reverse("integrations:status"))
        assert response.status_code == 200
        assert response.data["lexware"]["enabled"] is False
        assert response.data["clockify"]["enabled"] is False
        assert response.data["lexware"]["connected"] is False

    def test_status_requires_admin(self, member_client: APIClient) -> None:
        # A plain member is not an admin → forbidden on the integration centre.
        response = member_client.get(reverse("integrations:status"))
        assert response.status_code == 403


class TestConnectionTest:
    def test_lexware_disabled_returns_clear_error(self, auth_client: APIClient) -> None:
        response = auth_client.post(reverse("integrations:test", args=["lexware"]))
        assert response.status_code == 409
        assert response.data["error"]["code"] == "integration_disabled"

    @respx.mock
    @override_settings(LEXWARE_ENABLED=True, LEXWARE_API_KEY="test-key")
    def test_lexware_connection_success_caches_profile(
        self, auth_client: APIClient, workspace: Workspace, fast_limiter: None
    ) -> None:
        respx.get(f"{LEXWARE_BASE}/v1/profile").mock(
            return_value=httpx.Response(
                200,
                json={
                    "organizationId": "org-42",
                    "companyName": "Test GmbH",
                    "taxType": "net",
                    "smallBusiness": False,
                },
            )
        )
        response = auth_client.post(reverse("integrations:test", args=["lexware"]))
        assert response.status_code == 200
        assert response.data["company_name"] == "Test GmbH"

        profile = ProviderProfile.objects.get(workspace=workspace, provider=Provider.LEXWARE)
        assert profile.external_organization_id == "org-42"
        assert profile.tax_type == "net"
        assert profile.fetched_at is not None

    @respx.mock
    @override_settings(LEXWARE_ENABLED=True, LEXWARE_API_KEY="bad-key")
    def test_lexware_connection_failure_reports_502(
        self, auth_client: APIClient, fast_limiter: None
    ) -> None:
        respx.get(f"{LEXWARE_BASE}/v1/profile").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        response = auth_client.post(reverse("integrations:test", args=["lexware"]))
        assert response.status_code == 502
        assert response.data["error"]["code"] == "connection_failed"

    def test_unknown_provider_404(self, auth_client: APIClient) -> None:
        response = auth_client.post(reverse("integrations:test", args=["nonsense"]))
        assert response.status_code == 404


class TestConflictResolution:
    def test_list_and_resolve_conflict(
        self, auth_client: APIClient, workspace: Workspace, user: User
    ) -> None:
        conflict = SyncConflict.objects.create(
            workspace=workspace,
            provider=Provider.LEXWARE,
            resource_type="contact",
            local_object_type="crm.Client",
            local_snapshot={"name": "Local"},
            remote_snapshot={"name": "Remote"},
        )
        listing = auth_client.get(reverse("sync-conflict-list"))
        assert listing.data["count"] == 1

        response = auth_client.post(
            reverse("sync-conflict-resolve", args=[conflict.id]),
            {"resolution": "remote", "note": "Lexware gewinnt"},
            format="json",
        )
        assert response.status_code == 200

        conflict.refresh_from_db()
        assert conflict.resolution_status == ConflictResolutionStatus.RESOLVED_REMOTE
        assert conflict.resolved_by_id == user.pk

    def test_invalid_resolution_rejected(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        conflict = SyncConflict.objects.create(
            workspace=workspace,
            provider=Provider.LEXWARE,
            resource_type="contact",
            local_object_type="crm.Client",
        )
        response = auth_client.post(
            reverse("sync-conflict-resolve", args=[conflict.id]),
            {"resolution": "coinflip"},
            format="json",
        )
        assert response.status_code == 400


class TestClockifyClient:
    @respx.mock
    @override_settings(
        CLOCKIFY_ENABLED=True,
        CLOCKIFY_API_KEY="key-123",
    )
    def test_api_key_header_is_sent(self, fast_limiter: None) -> None:
        from apps.integrations.clockify.client import ClockifyClient

        route = respx.get("https://api.clockify.me/api/v1/user").mock(
            return_value=httpx.Response(200, json={"id": "u-1", "name": "Max"})
        )
        with ClockifyClient() as client:
            client.get_current_user()

        headers = route.calls.last.request.headers
        # Auth is the single X-Api-Key header (docs/integrations/clockify.md §2).
        assert headers["X-Api-Key"] == "key-123"
