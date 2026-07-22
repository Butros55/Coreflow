"""Reserve ledger: CRUD, permissions, and its effect on the reserve forecast."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.finance.models import ReserveTransfer, TaxProfile
from apps.finance.rulesets import install_default_rulesets
from apps.finance.services import compute_reserve

pytestmark = pytest.mark.django_db


class TestReserveTransferApi:
    def test_owner_creates_and_lists_transfers(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = auth_client.post(
            "/api/v1/reserve-transfers/",
            {"transfer_date": "2026-07-01", "amount": "500.00", "note": "Q2 USt"},
            format="json",
        )
        assert response.status_code == 201, response.content
        assert response.data["source"] == "manual"

        listing = auth_client.get("/api/v1/reserve-transfers/")
        assert listing.status_code == 200
        assert listing.data["count"] == 1
        assert listing.data["results"][0]["amount"] == "500.00"

    def test_zero_amount_is_rejected(self, auth_client: APIClient) -> None:
        response = auth_client.post(
            "/api/v1/reserve-transfers/",
            {"transfer_date": "2026-07-01", "amount": "0.00"},
            format="json",
        )
        assert response.status_code == 400

    def test_member_cannot_write_but_can_read(
        self, member_client: APIClient, workspace: Workspace
    ) -> None:
        response = member_client.post(
            "/api/v1/reserve-transfers/",
            {"transfer_date": "2026-07-01", "amount": "100.00"},
            format="json",
        )
        assert response.status_code == 403

        assert member_client.get("/api/v1/reserve-transfers/").status_code == 200

    def test_transfers_are_workspace_scoped(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        other_workspace: Workspace,
    ) -> None:
        ReserveTransfer.objects.create(
            workspace=other_workspace, transfer_date=date(2026, 1, 1), amount=Decimal("999")
        )
        listing = auth_client.get("/api/v1/reserve-transfers/")
        assert listing.data["count"] == 0


class TestReserveForecastWithLedger:
    def test_current_reserve_is_opening_plus_ledger(self, workspace: Workspace, user: User) -> None:
        install_default_rulesets()
        year = 2026
        TaxProfile.objects.create(
            workspace=workspace, tax_year=year, existing_reserve=Decimal("1000.00")
        )
        ReserveTransfer.objects.create(
            workspace=workspace, transfer_date=date(year, 3, 1), amount=Decimal("500.00")
        )
        ReserveTransfer.objects.create(
            workspace=workspace,
            transfer_date=date(year, 5, 1),
            amount=Decimal("-200.00"),
            note="Entnahme",
        )

        forecast = compute_reserve(workspace, year, today=date(year, 7, 1))

        assert forecast["available"] is True
        assert forecast["reserve_opening"] == "1000.00"
        assert forecast["reserve_transfers_total"] == "300.00"
        assert forecast["existing_reserve"] == "1300.00"
        assert forecast["last_transfer_date"] == "2026-05-01"
        # The gap uses the combined pot.
        expected_gap = Decimal(forecast["recommended_reserve"]) - Decimal("1300.00")
        assert Decimal(forecast["reserve_gap"]) == expected_gap

    def test_forecast_without_ledger_matches_profile_value(self, workspace: Workspace) -> None:
        install_default_rulesets()
        year = 2026
        TaxProfile.objects.create(
            workspace=workspace, tax_year=year, existing_reserve=Decimal("250.00")
        )
        forecast = compute_reserve(workspace, year, today=date(year, 7, 1))
        assert forecast["existing_reserve"] == "250.00"
        assert forecast["reserve_transfers_total"] == "0.00"
        assert forecast["last_transfer_date"] is None
