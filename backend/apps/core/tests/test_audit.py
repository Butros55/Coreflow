"""Audit log: recording at every wired action, admin-only read API."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace, WorkspaceMembership
from apps.core.audit import AuditLogEntry
from apps.integrations.models import Provider, SyncConflict

pytestmark = pytest.mark.django_db


class TestAuthAuditing:
    def test_login_success_is_recorded_with_ip(
        self, api_client: APIClient, user: User, owner_membership: WorkspaceMembership
    ) -> None:
        api_client.get(reverse("auth:csrf"))
        response = api_client.post(
            reverse("auth:login"),
            {"email": "owner@example.com", "password": "test-password-1234"},
            format="json",
            HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1",
        )
        assert response.status_code == 200

        entry = AuditLogEntry.objects.get(action="auth.login")
        assert entry.actor == user
        assert entry.ip_address == "203.0.113.7"

    def test_failed_login_is_recorded_without_actor(
        self, api_client: APIClient, user: User
    ) -> None:
        api_client.get(reverse("auth:csrf"))
        response = api_client.post(
            reverse("auth:login"),
            {"email": "owner@example.com", "password": "WRONG"},
            format="json",
        )
        assert response.status_code == 400

        entry = AuditLogEntry.objects.get(action="auth.login_failed")
        assert entry.actor is None
        assert entry.metadata["email"] == "owner@example.com"

    def test_logout_and_password_change_are_recorded(self, auth_client: APIClient) -> None:
        auth_client.post(
            reverse("auth:password-change"),
            {"current_password": "test-password-1234", "new_password": "next-password-5678"},
            format="json",
        )
        auth_client.post(reverse("auth:logout"))
        actions = set(AuditLogEntry.objects.values_list("action", flat=True))
        assert "auth.password_changed" in actions
        assert "auth.logout" in actions


class TestActionAuditing:
    def test_workspace_update_records_changed_fields(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = auth_client.patch(
            reverse("workspace-detail", args=[workspace.pk]),
            {"legal_name": "Neue Firma"},
            format="json",
        )
        assert response.status_code == 200
        entry = AuditLogEntry.objects.get(action="workspace.updated")
        assert entry.workspace == workspace
        assert entry.metadata["fields"] == ["legal_name"]

    def test_conflict_resolution_is_recorded(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        conflict = SyncConflict.objects.create(
            workspace=workspace,
            provider=Provider.CLOCKODO,
            resource_type="entry",
            local_object_type="timetracking.TimeEntry",
        )
        auth_client.post(
            reverse("sync-conflict-resolve", args=[conflict.pk]),
            {"resolution": "local"},
            format="json",
        )
        entry = AuditLogEntry.objects.get(action="integration.conflict_resolved")
        assert entry.target_id == str(conflict.pk)
        assert "local" in entry.summary


class TestAuditApi:
    def test_admin_sees_workspace_and_own_auth_events(
        self, auth_client: APIClient, workspace: Workspace, user: User
    ) -> None:
        AuditLogEntry.objects.create(workspace=workspace, actor=user, action="workspace.updated")
        AuditLogEntry.objects.create(workspace=None, actor=user, action="auth.login")
        # Unrelated global event of a non-member: invisible.
        stranger = User.objects.create_user(email="x@example.com", password="pw-123456789")
        AuditLogEntry.objects.create(workspace=None, actor=stranger, action="auth.login")

        response = auth_client.get(reverse("audit-log-list"))
        assert response.status_code == 200
        actions = [row["action"] for row in response.data["results"]]
        assert actions.count("auth.login") == 1
        assert "workspace.updated" in actions

    def test_member_cannot_read_audit_log(self, member_client: APIClient) -> None:
        assert member_client.get(reverse("audit-log-list")).status_code == 403

    def test_action_prefix_filter(
        self, auth_client: APIClient, workspace: Workspace, user: User
    ) -> None:
        AuditLogEntry.objects.create(workspace=workspace, actor=user, action="invoice.sent")
        AuditLogEntry.objects.create(
            workspace=workspace, actor=user, action="privacy.client_erased"
        )
        response = auth_client.get(reverse("audit-log-list"), {"action": "privacy."})
        assert [row["action"] for row in response.data["results"]] == ["privacy.client_erased"]

    def test_api_is_read_only(self, auth_client: APIClient, workspace: Workspace) -> None:
        response = auth_client.post(reverse("audit-log-list"), {"action": "fake"}, format="json")
        assert response.status_code == 405
