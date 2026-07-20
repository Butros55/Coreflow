"""Deletion semantics for projects and tasks."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.crm.models import Client
from apps.projects.models import Board, Project, Task
from apps.timetracking.models import TimeEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def project_with_task(workspace: Workspace, user: User) -> tuple[Project, Task, TimeEntry]:
    client = Client.objects.create(workspace=workspace, name="Löschkunde")
    project = Project.objects.create(workspace=workspace, client=client, name="Löschprojekt")
    board = Board.objects.create(workspace=workspace, project=project, name="Board")
    task = Task.objects.create(
        workspace=workspace,
        project=project,
        board=board,
        title="Löschaufgabe",
        created_by=user,
    )
    started_at = timezone.now() - timedelta(hours=1)
    entry = TimeEntry.objects.create(
        workspace=workspace,
        user=user,
        client=client,
        project=project,
        task=task,
        started_at=started_at,
        ended_at=started_at + timedelta(hours=1),
        duration_seconds=3600,
        hourly_rate="100.00",
        computed_amount="100.00",
    )
    return project, task, entry


def test_task_delete_keeps_time_entry_and_clears_reference(
    auth_client: APIClient, project_with_task: tuple[Project, Task, TimeEntry]
) -> None:
    _project, task, entry = project_with_task

    response = auth_client.delete(reverse("task-detail", args=[task.pk]))

    assert response.status_code == 204
    assert not Task.objects.filter(pk=task.pk).exists()
    entry.refresh_from_db()
    assert entry.task_id is None


def test_project_delete_cascades_work_structure_but_keeps_accounting_reference(
    auth_client: APIClient, project_with_task: tuple[Project, Task, TimeEntry]
) -> None:
    project, task, entry = project_with_task

    response = auth_client.delete(reverse("project-detail", args=[project.pk]))

    assert response.status_code == 204
    assert not Project.objects.filter(pk=project.pk).exists()
    assert not Task.objects.filter(pk=task.pk).exists()
    entry.refresh_from_db()
    assert entry.project_id is None
    assert entry.task_id is None


def test_readonly_member_cannot_delete_project(
    readonly_client: APIClient, project_with_task: tuple[Project, Task, TimeEntry]
) -> None:
    project, _task, _entry = project_with_task

    response = readonly_client.delete(reverse("project-detail", args=[project.pk]))

    assert response.status_code == 403
    assert Project.objects.filter(pk=project.pk).exists()
