"""Shared pytest fixtures.

Guiding rule: fixtures build objects through the real managers, so a test that
passes proves the real code path works — not that a factory can bypass it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.test import Client
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace, WorkspaceMembership, WorkspaceRole


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any test tries to open a real socket.

    Both integrations talk to production-only APIs (neither vendor offers a
    sandbox). A test that escapes its mock would hit a real account, so we make
    that impossible rather than merely discouraged.
    """
    import socket

    real_socket = socket.socket.connect

    def guard(self: Any, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        # Postgres/Redis in CI are reached over TCP and must stay allowed.
        if host in ("127.0.0.1", "::1", "localhost", "postgres", "redis"):
            return real_socket(self, address)
        raise RuntimeError(
            f"Test attempted a real network connection to {address!r}. "
            "Mock it with respx instead — the providers have no sandbox."
        )

    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture
def workspace(db: Any) -> Workspace:
    return Workspace.objects.create(
        name="Test Workspace",
        slug="test-workspace",
        legal_name="Test GmbH",
        default_currency="EUR",
        default_hourly_rate="100.00",
        default_payment_term_days=14,
    )


@pytest.fixture
def other_workspace(db: Any) -> Workspace:
    """A second tenant. Used to prove cross-workspace isolation."""
    return Workspace.objects.create(
        name="Other Workspace",
        slug="other-workspace",
        default_currency="EUR",
    )


@pytest.fixture
def user(db: Any) -> User:
    return User.objects.create_user(
        email="owner@example.com",
        password="test-password-1234",
        first_name="Olive",
        last_name="Owner",
    )


@pytest.fixture
def member_user(db: Any) -> User:
    return User.objects.create_user(
        email="member@example.com",
        password="test-password-1234",
        first_name="Mika",
        last_name="Member",
    )


@pytest.fixture
def readonly_user(db: Any) -> User:
    return User.objects.create_user(
        email="readonly@example.com",
        password="test-password-1234",
        first_name="Robin",
        last_name="Reader",
    )


@pytest.fixture
def outsider(db: Any) -> User:
    """Authenticated, but a member of no workspace under test."""
    return User.objects.create_user(email="outsider@example.com", password="test-password-1234")


@pytest.fixture
def owner_membership(workspace: Workspace, user: User) -> WorkspaceMembership:
    return WorkspaceMembership.objects.create(
        workspace=workspace, user=user, role=WorkspaceRole.OWNER, is_default=True
    )


@pytest.fixture
def member_membership(workspace: Workspace, member_user: User) -> WorkspaceMembership:
    return WorkspaceMembership.objects.create(
        workspace=workspace, user=member_user, role=WorkspaceRole.MEMBER, is_default=True
    )


@pytest.fixture
def readonly_membership(workspace: Workspace, readonly_user: User) -> WorkspaceMembership:
    return WorkspaceMembership.objects.create(
        workspace=workspace, user=readonly_user, role=WorkspaceRole.READONLY, is_default=True
    )


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def auth_client(
    api_client: APIClient, user: User, owner_membership: WorkspaceMembership
) -> APIClient:
    """API client authenticated as the workspace owner."""
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def member_client(member_user: User, member_membership: WorkspaceMembership) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=member_user)
    return client


@pytest.fixture
def readonly_client(readonly_user: User, readonly_membership: WorkspaceMembership) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=readonly_user)
    return client


@pytest.fixture
def django_client() -> Iterator[Client]:
    """Plain Django client, for tests that need real session/CSRF behaviour."""
    yield Client(enforce_csrf_checks=True)
