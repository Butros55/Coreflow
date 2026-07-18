"""The productive bootstrap command: real user + workspace, zero demo data."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounts.models import User, Workspace, WorkspaceMembership, WorkspaceRole
from apps.crm.models import Client
from apps.finance.models import TaxProfile, TaxRuleSet

pytestmark = pytest.mark.django_db


def run(*args: str) -> str:
    out = StringIO()
    call_command("bootstrap", *args, stdout=out)
    return out.getvalue()


class TestBootstrap:
    def test_creates_user_workspace_membership_and_tax_setup(self) -> None:
        output = run(
            "--email",
            "geret@example.com",
            "--workspace-name",
            "Wessling AI",
            "--owner-name",
            "Geret Wessling",
            "--small-business",
        )

        user = User.objects.get(email="geret@example.com")
        assert user.first_name == "Geret"
        assert user.is_superuser is False  # admin only with --superuser

        workspace = Workspace.objects.get(slug="wessling-ai")
        assert workspace.small_business is True
        membership = WorkspaceMembership.objects.get(workspace=workspace, user=user)
        assert membership.role == WorkspaceRole.OWNER
        assert membership.is_default is True

        assert TaxProfile.objects.filter(workspace=workspace).exists()
        assert TaxRuleSet.objects.count() > 0  # §32a data installed
        # The whole point: NO demo data.
        assert Client.objects.count() == 0
        assert "generated" in output

    def test_second_run_is_idempotent_and_never_resets_password(self) -> None:
        run("--email", "geret@example.com", "--workspace-name", "Wessling AI")
        user = User.objects.get(email="geret@example.com")
        user.set_password("mein-eigenes-passwort")
        user.save()

        output = run("--email", "geret@example.com", "--workspace-name", "Wessling AI")

        assert Workspace.objects.filter(name="Wessling AI").count() == 1
        user.refresh_from_db()
        assert user.check_password("mein-eigenes-passwort")
        assert "unchanged" in output

    def test_slug_collision_gets_a_suffix(self) -> None:
        run("--email", "a@example.com", "--workspace-name", "Meine Firma")
        run("--email", "b@example.com", "--workspace-name", "Meine  Firma!")  # same slug source

        slugs = set(Workspace.objects.values_list("slug", flat=True))
        assert "meine-firma" in slugs
        assert len(slugs) == 2

    def test_explicit_password_is_used(self) -> None:
        run(
            "--email",
            "c@example.com",
            "--workspace-name",
            "Firma C",
            "--password",
            "gewuenschtes-passwort-123",
        )
        user = User.objects.get(email="c@example.com")
        assert user.check_password("gewuenschtes-passwort-123")
