"""Timesheet exports use the list filters and never cross workspace boundaries."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.core.audit import AuditLogEntry
from apps.crm.models import Client
from apps.timetracking.models import TimeEntry

pytestmark = pytest.mark.django_db


def make_entry(
    workspace: Workspace,
    user: User,
    client: Client,
    *,
    started_at: datetime,
    description: str,
) -> TimeEntry:
    return TimeEntry.objects.create(
        workspace=workspace,
        user=user,
        client=client,
        description=description,
        started_at=started_at,
        ended_at=started_at + timedelta(hours=1),
        duration_seconds=3600,
        hourly_rate=Decimal("100.00"),
        computed_amount=Decimal("100.00"),
    )


class TestTimesheetExports:
    def test_csv_is_excel_friendly_filtered_and_workspace_scoped(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        other_workspace: Workspace,
        user: User,
    ) -> None:
        now = timezone.now().replace(microsecond=0)
        local_client = Client.objects.create(workspace=workspace, name="Müller & Söhne GmbH")
        foreign_client = Client.objects.create(workspace=other_workspace, name="Fremd AG")
        make_entry(
            workspace,
            user,
            local_client,
            started_at=now - timedelta(days=2),
            description="Im Zeitraum",
        )
        make_entry(
            workspace,
            user,
            local_client,
            started_at=now - timedelta(days=20),
            description="Zu alt",
        )
        make_entry(
            other_workspace,
            user,
            foreign_client,
            started_at=now - timedelta(days=2),
            description="Fremder Workspace",
        )

        response = auth_client.get(
            reverse("time-entry-export-csv"),
            {
                "time_from": (now - timedelta(days=7)).isoformat(),
                "time_to": now.isoformat(),
            },
        )

        assert response.status_code == 200
        assert response["Content-Type"] == "text/csv; charset=utf-8"
        assert "attachment" in response["Content-Disposition"]
        assert response.content.startswith(b"\xef\xbb\xbf")
        csv_text = response.content.decode("utf-8-sig")
        assert "Datum;Start;Ende;Kunde" in csv_text
        assert "Müller & Söhne GmbH" in csv_text
        assert "Im Zeitraum" in csv_text
        assert "Zu alt" not in csv_text
        assert "Fremder Workspace" not in csv_text
        audit = AuditLogEntry.objects.get(action="time.exported")
        assert audit.metadata["format"] == "csv"
        assert audit.metadata["count"] == 1

    def test_pdf_has_a_real_pdf_header_and_audits_the_export(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        user: User,
    ) -> None:
        customer = Client.objects.create(workspace=workspace, name="Acme GmbH")
        make_entry(
            workspace,
            user,
            customer,
            started_at=timezone.now() - timedelta(hours=2),
            description="Konzeption",
        )

        response = auth_client.get(reverse("time-entry-export-pdf"))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response.content.startswith(b"%PDF-")
        assert len(response.content) > 1_000
        assert AuditLogEntry.objects.filter(action="time.exported", metadata__format="pdf").exists()

    def test_running_timer_is_not_exported(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        user: User,
    ) -> None:
        customer = Client.objects.create(workspace=workspace, name="Timer GmbH")
        TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=customer,
            description="Noch laufend",
            started_at=timezone.now() - timedelta(minutes=15),
            ended_at=None,
            hourly_rate=Decimal("100.00"),
        )

        response = auth_client.get(reverse("time-entry-export-csv"))

        assert "Noch laufend" not in response.content.decode("utf-8-sig")
