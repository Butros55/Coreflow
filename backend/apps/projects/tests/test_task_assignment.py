from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace, WorkspaceMembership, WorkspaceRole
from apps.crm.models import Client
from apps.projects.models import Board, Project, Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def task(workspace: Workspace, user: User) -> Task:
    client = Client.objects.create(workspace=workspace, name="Kunde")
    project = Project.objects.create(workspace=workspace, client=client, name="Projekt")
    board = Board.objects.create(workspace=workspace, project=project, name="Board")
    return Task.objects.create(
        workspace=workspace,
        project=project,
        board=board,
        title="Zuweisbare Aufgabe",
        created_by=user,
    )


def test_assignment_makes_task_visible_in_my_tasks(
    auth_client: APIClient,
    member_client: APIClient,
    member_user: User,
    task: Task,
) -> None:
    response = auth_client.patch(
        reverse("task-detail", args=[task.pk]),
        {"assignees": [str(member_user.pk)]},
        format="json",
    )
    assert response.status_code == 200
    assert [str(value) for value in response.data["assignees"]] == [str(member_user.pk)]

    mine = member_client.get(reverse("task-list"), {"assigned_to_me": "true"})
    assert mine.status_code == 200
    assert [str(row["id"]) for row in mine.data["results"]] == [str(task.pk)]


def test_user_from_another_workspace_cannot_be_assigned(
    auth_client: APIClient,
    other_workspace: Workspace,
    outsider: User,
    task: Task,
) -> None:
    WorkspaceMembership.objects.create(
        workspace=other_workspace,
        user=outsider,
        role=WorkspaceRole.MEMBER,
        is_default=True,
    )
    response = auth_client.patch(
        reverse("task-detail", args=[task.pk]),
        {"assignees": [str(outsider.pk)]},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["error"]["code"] == "invalid"
    assert not task.assignees.exists()
