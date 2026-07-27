"""Company-settings saves: sloppy input is normalised, real errors are German
and concrete — never a bare "Validation failed"."""

from __future__ import annotations

from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Workspace

pytestmark = pytest.mark.django_db

WORKSPACE_HEADER = "X-Workspace-ID"


def _patch(client: APIClient, workspace: Workspace, payload: dict[str, Any]) -> Any:
    return client.patch(
        reverse("workspace-detail", args=[workspace.pk]),
        payload,
        format="json",
        headers={WORKSPACE_HEADER: str(workspace.pk)},
    )


class TestInputNormalisation:
    def test_website_without_scheme_is_accepted_and_normalised(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = _patch(auth_client, workspace, {"website": "meine-firma.de"})
        assert response.status_code == 200
        workspace.refresh_from_db()
        assert workspace.website == "https://meine-firma.de"

    def test_iban_and_bic_lose_spaces_and_casing(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = _patch(
            auth_client,
            workspace,
            {"bank_iban": "de89 3704 0044 0532 0130 00", "bank_bic": "genodem1gls"},
        )
        assert response.status_code == 200
        workspace.refresh_from_db()
        assert workspace.bank_iban == "DE89370400440532013000"
        assert workspace.bank_bic == "GENODEM1GLS"

    def test_email_is_stripped(self, auth_client: APIClient, workspace: Workspace) -> None:
        response = _patch(auth_client, workspace, {"email": "  mail@firma.de  "})
        assert response.status_code == 200
        workspace.refresh_from_db()
        assert workspace.email == "mail@firma.de"


class TestGermanValidationErrors:
    def test_invalid_iban_yields_concrete_german_message(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = _patch(auth_client, workspace, {"bank_iban": "DE123"})
        assert response.status_code == 400
        error = response.json()["error"]
        # The toast shows error.message — it must carry the real reason.
        assert "gültige IBAN" in error["message"]
        # The form highlights the field from error.detail.
        assert "bank_iban" in error["detail"]

    def test_invalid_bic_yields_concrete_german_message(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = _patch(auth_client, workspace, {"bank_bic": "X"})
        assert response.status_code == 400
        error = response.json()["error"]
        assert "gültigen BIC" in error["message"]
        assert "bank_bic" in error["detail"]

    def test_invalid_email_yields_localised_field_error(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = _patch(auth_client, workspace, {"email": "keine-mail"})
        assert response.status_code == 400
        error = response.json()["error"]
        assert error["message"] != "Validation failed."
        assert "E-Mail" in error["message"]  # DRF's own message, localised via de-de
        assert "email" in error["detail"]

    def test_multiple_invalid_fields_summarise_the_count(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = _patch(auth_client, workspace, {"email": "keine-mail", "bank_iban": "DE123"})
        assert response.status_code == 400
        error = response.json()["error"]
        assert "+1 weitere" in error["message"]
        assert set(error["detail"]) == {"email", "bank_iban"}

    def test_payment_term_above_limit_is_rejected_in_german(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = _patch(auth_client, workspace, {"default_payment_term_days": 700})
        assert response.status_code == 400
        error = response.json()["error"]
        assert "180 Tage" in error["message"]
        assert "default_payment_term_days" in error["detail"]
