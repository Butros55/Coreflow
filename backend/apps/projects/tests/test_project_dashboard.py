from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.crm.models import Client
from apps.invoicing.models import InvoiceStatus
from apps.invoicing.services import compose_invoice
from apps.invoicing.tests.test_invoicing import make_entry
from apps.projects.models import Board, Project, Task, TaskStatus
from apps.timetracking.models import BillingStatus

pytestmark = pytest.mark.django_db


def test_project_detail_exposes_task_time_invoice_and_paid_kpis(
    auth_client: APIClient,
    workspace: Workspace,
    user: User,
) -> None:
    client = Client.objects.create(
        workspace=workspace,
        name="Dashboard GmbH",
        default_hourly_rate="100.00",
    )
    project = Project.objects.create(
        workspace=workspace,
        client=client,
        name="Relaunch",
        budget_hours="10.00",
        budget_amount="1000.00",
    )
    board = Board.objects.create(workspace=workspace, project=project, name="Board")
    Task.objects.create(
        workspace=workspace,
        project=project,
        board=board,
        title="Überfällig",
        due_date=timezone.localdate() - timedelta(days=1),
        created_by=user,
    )
    Task.objects.create(
        workspace=workspace,
        project=project,
        board=board,
        title="Fertig",
        status=TaskStatus.DONE,
        created_by=user,
    )

    open_entry = make_entry(workspace, user, client, hours=2)
    open_entry.project = project
    open_entry.save(update_fields=["project", "updated_at"])
    paid_entry = make_entry(workspace, user, client, hours=3)
    paid_entry.project = project
    paid_entry.save(update_fields=["project", "updated_at"])
    invoice = compose_invoice(
        workspace=workspace,
        client=client,
        entry_ids=[str(paid_entry.pk)],
        grouping="lump_sum",
        project_id=str(project.pk),
    )
    invoice.status = InvoiceStatus.PAID
    invoice.invoice_date = timezone.localdate()
    invoice.save(update_fields=["status", "invoice_date", "updated_at"])
    paid_entry.billing_status = BillingStatus.BILLED
    paid_entry.save(update_fields=["billing_status", "updated_at"])

    response = auth_client.get(reverse("project-detail", args=[project.pk]))
    assert response.status_code == 200
    stats = response.data["stats"]
    assert stats["tasks"] == {
        "total": 2,
        "open": 1,
        "done": 1,
        "overdue": 1,
        "in_progress": 0,
        "review": 0,
        "stuck": 0,
    }
    assert stats["time"]["total_seconds"] == 5 * 3600
    assert stats["time"]["unbilled_seconds"] == 2 * 3600
    assert stats["time"]["billed_seconds"] == 3 * 3600
    assert stats["time"]["paid_seconds"] == 3 * 3600
    assert stats["time"]["paid_value"] == "300.00"
    assert stats["invoices"]["paid_count"] == 1
    assert stats["invoices"]["paid_net"] == "300.00"

    filtered = auth_client.get(reverse("invoice-list"), {"project": str(project.pk)})
    assert filtered.status_code == 200
    assert [row["id"] for row in filtered.data["results"]] == [str(invoice.pk)]
