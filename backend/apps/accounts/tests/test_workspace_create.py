"""Workspace creation from the app: onboarding, multi-workspace, separation."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace, WorkspaceMembership, WorkspaceRole
from apps.core.audit import AuditLogEntry
from apps.crm.models import Client
from apps.finance.models import TaxProfile, TaxRuleSet

pytestmark = pytest.mark.django_db

WORKSPACE_HEADER = "X-Workspace-ID"


@pytest.fixture
def fresh_client(db: object) -> APIClient:
    """An authenticated user WITHOUT any workspace — the onboarding case."""
    user = User.objects.create_user(email="fresh@example.com", password="pw-123456789")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


class TestCreateWorkspace:
    def test_user_without_workspace_can_create_their_first(self, fresh_client: APIClient) -> None:
        # The empty list must be reachable too (no workspace context exists yet).
        listing = fresh_client.get(reverse("workspace-list"))
        assert listing.status_code == 200

        response = fresh_client.post(
            reverse("workspace-list"),
            {"name": "Meine Firma", "small_business": True},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["name"] == "Meine Firma"

        workspace = Workspace.objects.get(slug="meine-firma")
        assert workspace.small_business is True
        membership = WorkspaceMembership.objects.get(workspace=workspace)
        assert membership.role == WorkspaceRole.OWNER
        assert membership.is_default is True  # first workspace becomes default
        assert TaxProfile.objects.filter(workspace=workspace).exists()
        assert TaxRuleSet.objects.count() > 0
        assert AuditLogEntry.objects.filter(action="workspace.created").exists()

    def test_second_workspace_does_not_steal_the_default(
        self, auth_client: APIClient, workspace: Workspace, user: User
    ) -> None:
        response = auth_client.post(
            reverse("workspace-list"), {"name": "Zweitfirma"}, format="json"
        )
        assert response.status_code == 201

        second = Workspace.objects.get(name="Zweitfirma")
        assert WorkspaceMembership.objects.get(workspace=second, user=user).is_default is False
        assert WorkspaceMembership.objects.get(workspace=workspace, user=user).is_default is True

    def test_slug_collision_gets_a_suffix(self, fresh_client: APIClient) -> None:
        fresh_client.post(reverse("workspace-list"), {"name": "Firma"}, format="json")
        fresh_client.post(reverse("workspace-list"), {"name": "Firma"}, format="json")
        slugs = set(Workspace.objects.values_list("slug", flat=True))
        assert {"firma", "firma-2"} <= slugs

    def test_anonymous_cannot_create(self, api_client: APIClient) -> None:
        response = api_client.post(reverse("workspace-list"), {"name": "X"}, format="json")
        assert response.status_code in (401, 403)

    def test_switching_the_default_works(
        self, auth_client: APIClient, workspace: Workspace, user: User
    ) -> None:
        """set-default is a POST — it was rejected with 405 before this fix."""
        auth_client.post(reverse("workspace-list"), {"name": "Zweitfirma"}, format="json")
        second = Workspace.objects.get(name="Zweitfirma")

        response = auth_client.post(reverse("workspace-set-default", args=[second.pk]))
        assert response.status_code == 200
        assert WorkspaceMembership.objects.get(workspace=second, user=user).is_default is True
        assert WorkspaceMembership.objects.get(workspace=workspace, user=user).is_default is False


class TestDataSeparation:
    def test_data_never_leaks_between_workspaces(
        self, auth_client: APIClient, workspace: Workspace, user: User
    ) -> None:
        Client.objects.create(workspace=workspace, name="Nur in Firma Eins")

        created = auth_client.post(reverse("workspace-list"), {"name": "Zweitfirma"}, format="json")
        second_id = created.data["id"]

        # Active workspace = first → the client is visible.
        first_list = auth_client.get(
            reverse("client-list"), headers={WORKSPACE_HEADER: str(workspace.pk)}
        )
        assert first_list.data["count"] == 1

        # Active workspace = second → completely empty, same user.
        second_list = auth_client.get(reverse("client-list"), headers={WORKSPACE_HEADER: second_id})
        assert second_list.status_code == 200
        assert second_list.data["count"] == 0

        # Creating in the second workspace stays in the second workspace.
        auth_client.post(
            reverse("client-list"),
            {"name": "Nur in Firma Zwei"},
            format="json",
            headers={WORKSPACE_HEADER: second_id},
        )
        assert Client.objects.filter(workspace=workspace).count() == 1
        assert Client.objects.filter(workspace_id=second_id).count() == 1
