"""Appointments, ICS round-trip, and file upload validation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.crm.models import Client
from apps.scheduling.ics import appointments_to_ics, parse_ics
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db


def make_appointment(workspace: Workspace, **overrides: object) -> Appointment:
    start = timezone.now() + timedelta(days=1)
    defaults = {
        "workspace": workspace,
        "title": "Kickoff",
        "starts_at": start,
        "ends_at": start + timedelta(hours=1),
    }
    return Appointment.objects.create(**{**defaults, **overrides})


class TestAppointments:
    def test_create_adds_creator_as_participant(self, auth_client: APIClient, user: User) -> None:
        start = timezone.now() + timedelta(days=2)
        response = auth_client.post(
            reverse("appointment-list"),
            {
                "title": "Beratung",
                "starts_at": start.isoformat(),
                "ends_at": (start + timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        assert response.status_code == 201
        appointment = Appointment.objects.get(pk=response.data["id"])
        assert user in appointment.participants.all()

    def test_end_must_be_after_start(self, auth_client: APIClient) -> None:
        start = timezone.now()
        response = auth_client.post(
            reverse("appointment-list"),
            {
                "title": "Kaputt",
                "starts_at": start.isoformat(),
                "ends_at": (start - timedelta(hours=1)).isoformat(),
            },
            format="json",
        )
        assert response.status_code == 400

    def test_date_range_filter(self, auth_client: APIClient, workspace: Workspace) -> None:
        make_appointment(
            workspace,
            title="Bald",
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1, hours=1),
        )
        make_appointment(
            workspace,
            title="Später",
            starts_at=timezone.now() + timedelta(days=30),
            ends_at=timezone.now() + timedelta(days=30, hours=1),
        )
        response = auth_client.get(
            reverse("appointment-list"),
            {
                "from_date": timezone.now().isoformat(),
                "to_date": (timezone.now() + timedelta(days=7)).isoformat(),
            },
        )
        titles = {row["title"] for row in response.data["results"]}
        assert "Bald" in titles
        assert "Später" not in titles

    def test_create_task_from_appointment(
        self, auth_client: APIClient, workspace: Workspace, user: User
    ) -> None:
        from apps.projects.models import Board, Project, Task

        client = Client.objects.create(workspace=workspace, name="Kunde")
        project = Project.objects.create(workspace=workspace, client=client, name="Projekt")
        Board.objects.create(workspace=workspace, project=project, name="Board")
        appointment = make_appointment(workspace, project=project, next_steps="Angebot nachfassen")
        response = auth_client.post(reverse("appointment-create-task", args=[appointment.id]))
        assert response.status_code == 200
        task = Task.objects.get(pk=response.data["task_id"])
        assert task.project_id == project.pk
        assert "Angebot nachfassen" in task.description

    def test_workspace_isolation(self, auth_client: APIClient, other_workspace: Workspace) -> None:
        foreign = make_appointment(other_workspace, title="Fremd")
        assert auth_client.get(reverse("appointment-list")).data["count"] == 0
        assert auth_client.get(reverse("appointment-detail", args=[foreign.id])).status_code == 404


class TestICS:
    def test_round_trip_preserves_appointment(self, workspace: Workspace) -> None:
        appointment = make_appointment(workspace, title="Sprint Review", location="Videocall")
        ics = appointments_to_ics([appointment])
        assert b"Sprint Review" in ics

        events = parse_ics(ics)
        assert len(events) == 1
        assert events[0]["title"] == "Sprint Review"
        assert events[0]["uid"] == appointment.ics_uid

    def test_import_is_idempotent_on_uid(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        appointment = make_appointment(workspace, title="Original")
        ics = appointments_to_ics([appointment]).decode("utf-8")

        # Importing the same UID updates, does not duplicate.
        response = auth_client.post(reverse("appointment-import-ics"), {"ics": ics}, format="json")
        assert response.status_code == 200
        assert response.data["updated"] == 1
        assert response.data["created"] == 0
        assert Appointment.objects.filter(workspace=workspace).count() == 1

    def test_export_returns_calendar_file(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        make_appointment(workspace, title="Termin")
        response = auth_client.get(reverse("appointment-export-ics"))
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/calendar")
        assert b"BEGIN:VCALENDAR" in response.getvalue()


class TestFileUpload:
    def _upload(self, client: APIClient, filename: str, content: bytes = b"data") -> Any:
        from django.core.files.uploadedfile import SimpleUploadedFile

        return client.post(
            reverse("file-list"),
            {"file": SimpleUploadedFile(filename, content)},
            format="multipart",
        )

    def test_upload_stores_metadata_and_checksum(self, auth_client: APIClient) -> None:
        response = self._upload(auth_client, "vertrag.pdf", b"%PDF-1.7 content")
        assert response.status_code == 201
        assert response.data["filename"] == "vertrag.pdf"
        assert response.data["size_bytes"] == len(b"%PDF-1.7 content")

    def test_disallowed_extension_is_rejected(self, auth_client: APIClient) -> None:
        response = self._upload(auth_client, "malware.exe", b"MZ")
        assert response.status_code == 400

    def test_oversized_file_is_rejected(self, auth_client: APIClient, settings: object) -> None:
        settings.FILE_UPLOAD_MAX_BYTES = 10  # type: ignore[attr-defined]
        response = self._upload(auth_client, "big.pdf", b"way too many bytes")
        assert response.status_code == 400

    def test_readonly_member_cannot_upload(self, readonly_client: APIClient) -> None:
        response = self._upload(readonly_client, "note.txt", b"hi")
        assert response.status_code == 403

    def test_download_works_without_workspace_header(self, auth_client: APIClient) -> None:
        """window.open / <a href> cannot send X-Workspace-ID — the download
        resolves via memberships instead, and serves inline for viewing."""
        upload = self._upload(auth_client, "ansicht.pdf", b"%PDF-1.7 inline")
        file_id = upload.data["id"]

        auth_client.credentials()  # strip default headers incl. the workspace id
        response = auth_client.get(reverse("file-download", args=[file_id]))
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == b"%PDF-1.7 inline"  # type: ignore[attr-defined]
        assert "attachment" not in response.headers.get("Content-Disposition", "")

    def test_download_denied_for_non_members(self, auth_client: APIClient, outsider: Any) -> None:
        upload = self._upload(auth_client, "geheim.pdf", b"%PDF-1.7 secret")
        file_id = upload.data["id"]

        stranger = APIClient()
        stranger.force_authenticate(user=outsider)
        assert stranger.get(reverse("file-download", args=[file_id])).status_code == 404
