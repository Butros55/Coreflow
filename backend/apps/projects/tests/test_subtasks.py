"""Subtask API constraints: same project/board and an acyclic parent graph."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.crm.models import Client
from apps.projects.models import Board, Project, Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def boards(workspace: Workspace) -> tuple[Board, Board]:
    customer = Client.objects.create(workspace=workspace, name="Kunde")
    first_project = Project.objects.create(workspace=workspace, client=customer, name="Projekt A")
    second_project = Project.objects.create(workspace=workspace, client=customer, name="Projekt B")
    return (
        Board.objects.create(workspace=workspace, project=first_project, name="Board A"),
        Board.objects.create(workspace=workspace, project=second_project, name="Board B"),
    )


def task(board: Board, user: User, title: str, parent: Task | None = None) -> Task:
    return Task.objects.create(
        workspace=board.workspace,
        project=board.project,
        board=board,
        title=title,
        parent=parent,
        created_by=user,
    )


class TestSubtasks:
    def test_valid_subtask_exposes_parent_title(
        self, auth_client: APIClient, boards: tuple[Board, Board], user: User
    ) -> None:
        board, _ = boards
        parent = task(board, user, "Übergeordnet")

        response = auth_client.post(
            reverse("task-list"),
            {
                "project": str(board.project_id),
                "board": str(board.pk),
                "parent": str(parent.pk),
                "title": "Unteraufgabe",
            },
        )

        assert response.status_code == 201
        assert response.data["parent"] == parent.pk
        assert response.data["parent_title"] == "Übergeordnet"

    def test_parent_must_belong_to_same_project_and_board(
        self, auth_client: APIClient, boards: tuple[Board, Board], user: User
    ) -> None:
        first, second = boards
        parent = task(first, user, "Falscher Parent")

        response = auth_client.post(
            reverse("task-list"),
            {
                "project": str(second.project_id),
                "board": str(second.pk),
                "parent": str(parent.pk),
                "title": "Ungültig",
            },
        )

        assert response.status_code == 400
        assert "parent" in response.data["error"]["detail"]

    def test_self_parent_and_longer_cycle_are_rejected(
        self, auth_client: APIClient, boards: tuple[Board, Board], user: User
    ) -> None:
        board, _ = boards
        parent = task(board, user, "Parent")
        child = task(board, user, "Child", parent=parent)

        self_response = auth_client.patch(
            reverse("task-detail", args=[child.pk]),
            {"parent": str(child.pk)},
        )
        cycle_response = auth_client.patch(
            reverse("task-detail", args=[parent.pk]),
            {"parent": str(child.pk)},
        )

        assert self_response.status_code == 400
        assert cycle_response.status_code == 400
        parent.refresh_from_db()
        assert parent.parent is None
