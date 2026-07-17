"""Authentication endpoint tests."""

from __future__ import annotations

from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace, WorkspaceMembership, WorkspaceRole

pytestmark = pytest.mark.django_db


class TestLogin:
    def test_login_succeeds_with_valid_credentials(
        self, api_client: APIClient, user: User, owner_membership: WorkspaceMembership
    ) -> None:
        response = api_client.post(
            reverse("auth:login"),
            {"email": "owner@example.com", "password": "test-password-1234"},
        )
        assert response.status_code == 200
        assert response.data["user"]["email"] == "owner@example.com"
        assert response.data["role"] == WorkspaceRole.OWNER
        assert response.data["workspace"]["slug"] == "test-workspace"

    def test_login_is_case_insensitive_on_email(
        self, api_client: APIClient, user: User, owner_membership: WorkspaceMembership
    ) -> None:
        response = api_client.post(
            reverse("auth:login"),
            {"email": "OWNER@EXAMPLE.COM", "password": "test-password-1234"},
        )
        assert response.status_code == 200

    def test_login_fails_with_wrong_password(self, api_client: APIClient, user: User) -> None:
        response = api_client.post(
            reverse("auth:login"), {"email": "owner@example.com", "password": "wrong"}
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "invalid_credentials"

    def test_login_does_not_reveal_whether_the_account_exists(
        self, api_client: APIClient, user: User
    ) -> None:
        """Wrong password and unknown user must be indistinguishable.

        Differing responses let an attacker enumerate valid customer emails.
        """
        wrong_password = api_client.post(
            reverse("auth:login"), {"email": "owner@example.com", "password": "wrong"}
        )
        unknown_user = api_client.post(
            reverse("auth:login"), {"email": "nobody@example.com", "password": "wrong"}
        )
        assert wrong_password.status_code == unknown_user.status_code

        # request_id is intentionally unique per request; everything the client
        # could distinguish the two cases by must be identical.
        def comparable(response: Any) -> dict[str, Any]:
            error = dict(response.data["error"])
            error.pop("request_id", None)
            return error

        assert comparable(wrong_password) == comparable(unknown_user)
        assert comparable(wrong_password)["code"] == "invalid_credentials"

    def test_inactive_user_cannot_log_in(self, api_client: APIClient, user: User) -> None:
        user.is_active = False
        user.save(update_fields=["is_active"])
        response = api_client.post(
            reverse("auth:login"),
            {"email": "owner@example.com", "password": "test-password-1234"},
        )
        assert response.status_code == 400

    def test_login_without_membership_returns_null_workspace(
        self, api_client: APIClient, outsider: User
    ) -> None:
        """Authentication and authorisation are separate: logging in is allowed,
        but with no workspace there is nothing to see."""
        response = api_client.post(
            reverse("auth:login"),
            {"email": "outsider@example.com", "password": "test-password-1234"},
        )
        assert response.status_code == 200
        assert response.data["workspace"] is None
        assert response.data["role"] is None
        assert response.data["permissions"] == {}


class TestSession:
    def test_session_requires_authentication(self, api_client: APIClient) -> None:
        response = api_client.get(reverse("auth:session"))
        # 401 not 403: the SPA distinguishes "log in" from "forbidden".
        assert response.status_code == 401

    def test_session_returns_permissions_for_role(self, readonly_client: APIClient) -> None:
        response = readonly_client.get(reverse("auth:session"))
        assert response.status_code == 200
        perms = response.data["permissions"]
        assert perms["can_read"] is True
        assert perms["can_write"] is False
        assert perms["can_manage_settings"] is False
        assert perms["can_delete_workspace"] is False

    def test_owner_has_all_permissions(self, auth_client: APIClient) -> None:
        response = auth_client.get(reverse("auth:session"))
        perms = response.data["permissions"]
        assert all(perms.values())

    def test_session_lists_all_memberships(
        self,
        auth_client: APIClient,
        user: User,
        other_workspace: Workspace,
    ) -> None:
        WorkspaceMembership.objects.create(
            workspace=other_workspace, user=user, role=WorkspaceRole.MEMBER
        )
        response = auth_client.get(reverse("auth:session"))
        slugs = {w["slug"] for w in response.data["workspaces"]}
        assert slugs == {"test-workspace", "other-workspace"}


class TestWorkspaceHeaderResolution:
    def test_header_selects_the_workspace(
        self, auth_client: APIClient, user: User, other_workspace: Workspace
    ) -> None:
        WorkspaceMembership.objects.create(
            workspace=other_workspace, user=user, role=WorkspaceRole.MEMBER
        )
        response = auth_client.get(
            reverse("auth:session"), headers={"X-Workspace-ID": str(other_workspace.pk)}
        )
        assert response.data["workspace"]["slug"] == "other-workspace"
        assert response.data["role"] == WorkspaceRole.MEMBER

    def test_header_for_a_workspace_you_do_not_belong_to_is_refused(
        self, auth_client: APIClient, other_workspace: Workspace
    ) -> None:
        """The header must never grant access — it only selects among memberships."""
        response = auth_client.get(
            reverse("auth:session"), headers={"X-Workspace-ID": str(other_workspace.pk)}
        )
        assert response.status_code == 200
        assert response.data["workspace"] is None
        assert response.data["role"] is None

    def test_malformed_header_denies_rather_than_falling_back(
        self, auth_client: APIClient, owner_membership: WorkspaceMembership
    ) -> None:
        """A garbage header must not silently resolve to the default workspace.

        Falling back would mean a client bug writes to the wrong tenant.
        """
        response = auth_client.get(
            reverse("auth:session"), headers={"X-Workspace-ID": "not-a-uuid"}
        )
        assert response.data["workspace"] is None

    def test_unknown_workspace_id_denies(self, auth_client: APIClient) -> None:
        import uuid

        response = auth_client.get(
            reverse("auth:session"), headers={"X-Workspace-ID": str(uuid.uuid4())}
        )
        assert response.data["workspace"] is None


class TestLogout:
    def test_logout_clears_the_session(
        self, api_client: APIClient, user: User, owner_membership: WorkspaceMembership
    ) -> None:
        api_client.post(
            reverse("auth:login"),
            {"email": "owner@example.com", "password": "test-password-1234"},
        )
        assert api_client.get(reverse("auth:session")).status_code == 200

        assert api_client.post(reverse("auth:logout")).status_code == 204
        assert api_client.get(reverse("auth:session")).status_code == 401


class TestPasswordChange:
    def test_password_change_requires_the_current_password(self, auth_client: APIClient) -> None:
        response = auth_client.post(
            reverse("auth:password-change"),
            {"current_password": "wrong", "new_password": "a-brand-new-password-9"},
        )
        assert response.status_code == 400

    def test_password_change_succeeds_and_keeps_session(
        self, auth_client: APIClient, user: User
    ) -> None:
        response = auth_client.post(
            reverse("auth:password-change"),
            {"current_password": "test-password-1234", "new_password": "a-brand-new-password-9"},
        )
        assert response.status_code == 204

        user.refresh_from_db()
        assert user.check_password("a-brand-new-password-9")
        # Changing your own password must not log you out.
        assert auth_client.get(reverse("auth:session")).status_code == 200

    def test_new_password_must_pass_validators(self, auth_client: APIClient) -> None:
        response = auth_client.post(
            reverse("auth:password-change"),
            {"current_password": "test-password-1234", "new_password": "password123"},
        )
        assert response.status_code == 400


class TestCsrf:
    def test_csrf_endpoint_issues_a_cookie(self, api_client: APIClient) -> None:
        response = api_client.get(reverse("auth:csrf"))
        assert response.status_code == 200
        assert "csrf_token" in response.data

    def test_unsafe_request_without_csrf_token_is_rejected(
        self, django_client: Any, user: User, owner_membership: WorkspaceMembership
    ) -> None:
        """Session auth must enforce CSRF on writes.

        Uses the plain Django client with enforce_csrf_checks=True, because
        APIClient.force_authenticate deliberately bypasses CSRF.
        """
        django_client.force_login(user)
        response = django_client.post(
            reverse("auth:password-change"),
            data={"current_password": "test-password-1234", "new_password": "another-password-12"},
            content_type="application/json",
        )
        assert response.status_code == 403
