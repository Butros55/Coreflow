"""Workspace export/import: completeness, roundtrip, isolation, permissions."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.core.models import WorkspaceScopedModel
from apps.core.portability import (
    EXPORT_EXCLUDED,
    EXPORT_MODELS,
    export_workspace,
    import_workspace,
)
from apps.crm.models import Client
from apps.invoicing.models import Invoice, InvoiceStatus
from apps.projects.models import Board, Project, Task
from apps.timetracking.models import BillingStatus, TimeEntry

pytestmark = pytest.mark.django_db


def test_every_workspace_scoped_model_has_an_export_decision() -> None:
    """A new workspace model must be exported or explicitly excluded."""
    covered = {label.lower() for label in EXPORT_MODELS} | {
        label.lower() for label in EXPORT_EXCLUDED
    }
    concrete = {
        model._meta.label_lower
        for model in django_apps.get_models()
        if issubclass(model, WorkspaceScopedModel) and not model._meta.abstract
    }
    missing = concrete - covered
    assert not missing, f"Modelle ohne Export-Entscheidung: {sorted(missing)}"


@pytest.fixture
def seeded(workspace: Workspace, user: User) -> dict[str, object]:
    client = Client.objects.create(workspace=workspace, name="Acme GmbH", currency="EUR")
    project = Project.objects.create(workspace=workspace, client=client, name="Website")
    board = Board.objects.create(workspace=workspace, project=project, name="Hauptboard")
    parent = Task.objects.create(
        workspace=workspace, project=project, board=board, title="Eltern-Task"
    )
    child = Task.objects.create(
        workspace=workspace, project=project, board=board, title="Kind-Task", parent=parent
    )
    child.assignees.add(user)
    started = timezone.now() - timedelta(days=1)
    entry = TimeEntry.objects.create(
        workspace=workspace,
        user=user,
        client=client,
        project=project,
        started_at=started,
        ended_at=started + timedelta(hours=2),
        duration_seconds=7200,
        hourly_rate=Decimal("100.00"),
        computed_amount=Decimal("200.00"),
        billable=True,
        billing_status=BillingStatus.OPEN,
    )
    invoice = Invoice.objects.create(
        workspace=workspace,
        client=client,
        project=project,
        status=InvoiceStatus.OPEN,
        net_amount=Decimal("200.00"),
    )
    return {
        "client": client,
        "project": project,
        "child": child,
        "parent": parent,
        "entry": entry,
        "invoice": invoice,
    }


class TestRoundtrip:
    def test_export_import_restores_deleted_data(
        self, workspace: Workspace, user: User, seeded: dict[str, object]
    ) -> None:
        # Serialize + parse: the same JSON roundtrip a real export file takes.
        payload = json.loads(json.dumps(export_workspace(workspace), cls=DjangoJSONEncoder))
        assert payload["counts"]["projects.Task"] == 2

        # Wipe: user "loses" everything.
        Task.objects.filter(workspace=workspace).delete()
        Invoice.objects.filter(workspace=workspace).delete()
        TimeEntry.objects.filter(workspace=workspace).delete()
        Project.objects.filter(workspace=workspace).delete()
        Client.objects.filter(workspace=workspace).delete()

        result = import_workspace(workspace, payload, user)

        assert result["imported"]["projects.Task"] == 2
        child = Task.objects.get(title="Kind-Task")
        assert child.parent is not None and child.parent.title == "Eltern-Task"
        assert list(child.assignees.values_list("pk", flat=True)) == [user.pk]
        entry = TimeEntry.objects.get(workspace=workspace)
        assert entry.project is not None and entry.project.name == "Website"
        invoice = Invoice.objects.get(workspace=workspace)
        assert invoice.project_id == entry.project_id

    def test_import_is_upsert_not_duplicate(
        self, workspace: Workspace, user: User, seeded: dict[str, object]
    ) -> None:
        payload = json.loads(json.dumps(export_workspace(workspace), cls=DjangoJSONEncoder))
        import_workspace(workspace, payload, user)
        assert Task.objects.filter(workspace=workspace).count() == 2
        assert Client.objects.filter(workspace=workspace).count() == 1

    def test_unknown_user_references_fall_back_to_importer(
        self, workspace: Workspace, user: User, seeded: dict[str, object]
    ) -> None:
        payload = json.loads(json.dumps(export_workspace(workspace), cls=DjangoJSONEncoder))
        ghost = "00000000-0000-0000-0000-00000000dead"
        for row in payload["data"]["timetracking.TimeEntry"]:
            row["fields"]["user"] = ghost

        TimeEntry.objects.filter(workspace=workspace).delete()
        import_workspace(workspace, payload, user)

        entry = TimeEntry.objects.get(workspace=workspace)
        assert entry.user_id == user.pk

    def test_import_pins_everything_to_target_workspace(
        self,
        workspace: Workspace,
        other_workspace: Workspace,
        user: User,
        seeded: dict[str, object],
    ) -> None:
        payload = json.loads(json.dumps(export_workspace(workspace), cls=DjangoJSONEncoder))
        import_workspace(other_workspace, payload, user)
        # Same pks now live in the other workspace (moved by upsert), never a
        # third copy anywhere.
        assert Client.objects.filter(workspace=other_workspace, name="Acme GmbH").exists()


class TestEndpoints:
    def test_admin_can_export_download(
        self, auth_client: APIClient, workspace: Workspace, seeded: dict[str, object]
    ) -> None:
        response = auth_client.get("/api/v1/workspace-data/export")
        assert response.status_code == 200
        assert "attachment" in response["Content-Disposition"]
        payload = json.loads(response.content)
        assert payload["format"] == "coreflow-workspace-export"
        assert payload["counts"]["crm.Client"] == 1

    def test_member_cannot_export(self, member_client: APIClient) -> None:
        assert member_client.get("/api/v1/workspace-data/export").status_code == 403

    def test_import_endpoint_roundtrip(
        self, auth_client: APIClient, workspace: Workspace, seeded: dict[str, object]
    ) -> None:
        exported = auth_client.get("/api/v1/workspace-data/export").content
        Task.objects.filter(workspace=workspace).delete()

        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("export.json", exported, content_type="application/json")
        response = auth_client.post(
            "/api/v1/workspace-data/import", {"file": upload}, format="multipart"
        )
        assert response.status_code == 200, response.content
        assert response.data["imported"]["projects.Task"] == 2
        assert Task.objects.filter(workspace=workspace).count() == 2

    def test_import_rejects_garbage(self, auth_client: APIClient) -> None:
        response = auth_client.post(
            "/api/v1/workspace-data/import", {"nonsense": True}, format="json"
        )
        assert response.status_code == 400
