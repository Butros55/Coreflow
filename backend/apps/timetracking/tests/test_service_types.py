"""Service-type API: duplicate names must fail as a clear 400, not a DB 500."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Workspace
from apps.timetracking.models import ServiceType

pytestmark = pytest.mark.django_db

WORKSPACE_HEADER = "X-Workspace-ID"


class TestServiceTypeUniqueName:
    def test_duplicate_name_returns_german_validation_error(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        headers = {WORKSPACE_HEADER: str(workspace.pk)}
        first = auth_client.post(
            reverse("service-type-list"), {"name": "Entwicklung"}, format="json", headers=headers
        )
        assert first.status_code == 201

        # Case-insensitive: "entwicklung" would be indistinguishable in the UI.
        duplicate = auth_client.post(
            reverse("service-type-list"), {"name": "entwicklung"}, format="json", headers=headers
        )
        assert duplicate.status_code == 400
        error = duplicate.json()["error"]
        assert "existiert bereits" in error["message"]
        assert "name" in error["detail"]
        assert ServiceType.objects.filter(workspace=workspace).count() == 1

    def test_rename_to_own_name_still_allowed(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        headers = {WORKSPACE_HEADER: str(workspace.pk)}
        created = auth_client.post(
            reverse("service-type-list"), {"name": "Beratung"}, format="json", headers=headers
        )
        service_id = created.json()["id"]

        response = auth_client.patch(
            reverse("service-type-detail", args=[service_id]),
            {"name": "Beratung", "description": "Strategie"},
            format="json",
            headers=headers,
        )
        assert response.status_code == 200
