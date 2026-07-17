"""Kanban move endpoint: fractional ranking, cross-column moves, rebalancing."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.crm.models import Client
from apps.projects.models import Board, Project, Task, TaskStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def board(workspace: Workspace) -> Board:
    client = Client.objects.create(workspace=workspace, name="Kunde")
    project = Project.objects.create(workspace=workspace, client=client, name="Projekt")
    return Board.objects.create(workspace=workspace, project=project, name="Board")


def make_task(board: Board, user: User, title: str, status: str, order: str) -> Task:
    return Task.objects.create(
        workspace=board.workspace,
        project=board.project,
        board=board,
        title=title,
        status=status,
        order=Decimal(order),
        created_by=user,
    )


def column_titles(board: Board, status: str) -> list[str]:
    return list(
        Task.objects.filter(board=board, status=status)
        .order_by("order")
        .values_list("title", flat=True)
    )


class TestMove:
    def test_move_between_two_tasks_takes_the_midpoint(
        self, auth_client: APIClient, board: Board, user: User
    ) -> None:
        a = make_task(board, user, "A", TaskStatus.TODO, "1024")
        make_task(board, user, "B", TaskStatus.TODO, "2048")
        c = make_task(board, user, "C", TaskStatus.TODO, "3072")

        response = auth_client.post(
            reverse("task-move", args=[c.pk]),
            {"status": TaskStatus.TODO, "after": str(a.pk)},
        )
        assert response.status_code == 200
        assert column_titles(board, TaskStatus.TODO) == ["A", "C", "B"]
        c.refresh_from_db()
        assert c.order == Decimal("1536")  # (1024+2048)/2 — exactly one row changed

    def test_move_to_top(self, auth_client: APIClient, board: Board, user: User) -> None:
        make_task(board, user, "A", TaskStatus.TODO, "1024")
        b = make_task(board, user, "B", TaskStatus.TODO, "2048")

        response = auth_client.post(
            reverse("task-move", args=[b.pk]), {"status": TaskStatus.TODO, "after": None}
        )
        assert response.status_code == 200
        assert column_titles(board, TaskStatus.TODO) == ["B", "A"]

    def test_move_to_bottom_appends_a_full_step(
        self, auth_client: APIClient, board: Board, user: User
    ) -> None:
        a = make_task(board, user, "A", TaskStatus.TODO, "1024")
        b = make_task(board, user, "B", TaskStatus.TODO, "2048")

        assert b.pk  # anchor referenced below
        auth_client.post(
            reverse("task-move", args=[a.pk]), {"status": TaskStatus.TODO, "after": str(b.pk)}
        )
        assert column_titles(board, TaskStatus.TODO) == ["B", "A"]
        a.refresh_from_db()
        assert a.order == Decimal("3072")

    def test_cross_column_move_changes_status(
        self, auth_client: APIClient, board: Board, user: User
    ) -> None:
        task = make_task(board, user, "A", TaskStatus.TODO, "1024")
        make_task(board, user, "X", TaskStatus.IN_PROGRESS, "1024")

        response = auth_client.post(
            reverse("task-move", args=[task.pk]),
            {"status": TaskStatus.IN_PROGRESS, "after": None},
        )
        assert response.status_code == 200
        assert response.data["status"] == TaskStatus.IN_PROGRESS
        assert column_titles(board, TaskStatus.IN_PROGRESS) == ["A", "X"]
        assert column_titles(board, TaskStatus.TODO) == []

    def test_move_into_empty_column(self, auth_client: APIClient, board: Board, user: User) -> None:
        task = make_task(board, user, "A", TaskStatus.TODO, "1024")
        response = auth_client.post(
            reverse("task-move", args=[task.pk]), {"status": TaskStatus.REVIEW, "after": None}
        )
        assert response.status_code == 200
        task.refresh_from_db()
        assert task.status == TaskStatus.REVIEW
        assert task.order == Decimal("1024")

    def test_anchor_from_another_column_is_rejected(
        self, auth_client: APIClient, board: Board, user: User
    ) -> None:
        task = make_task(board, user, "A", TaskStatus.TODO, "1024")
        anchor = make_task(board, user, "X", TaskStatus.DONE, "1024")
        response = auth_client.post(
            reverse("task-move", args=[task.pk]),
            {"status": TaskStatus.TODO, "after": str(anchor.pk)},
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "invalid_anchor"

    def test_exhausted_gap_triggers_rebalance_and_still_places_correctly(
        self, auth_client: APIClient, board: Board, user: User
    ) -> None:
        """Neighbours closer than the epsilon force a column renumbering; the
        move must still land in the right slot afterwards."""
        a = make_task(board, user, "A", TaskStatus.TODO, "1.0000000001")
        make_task(board, user, "B", TaskStatus.TODO, "1.0000000002")
        c = make_task(board, user, "C", TaskStatus.TODO, "3000")

        response = auth_client.post(
            reverse("task-move", args=[c.pk]), {"status": TaskStatus.TODO, "after": str(a.pk)}
        )
        assert response.status_code == 200
        assert column_titles(board, TaskStatus.TODO) == ["A", "C", "B"]
        orders = list(
            Task.objects.filter(board=board, status=TaskStatus.TODO)
            .order_by("order")
            .values_list("order", flat=True)
        )
        # After rebalancing, gaps are healthy again.
        assert orders[1] - orders[0] > Decimal("1")
        assert orders[2] - orders[1] > Decimal("1")

    def test_move_is_workspace_scoped(
        self, auth_client: APIClient, other_workspace: Workspace, user: User
    ) -> None:
        client = Client.objects.create(workspace=other_workspace, name="Fremd")
        project = Project.objects.create(workspace=other_workspace, client=client, name="P")
        foreign_board = Board.objects.create(workspace=other_workspace, project=project, name="B")
        foreign = Task.objects.create(
            workspace=other_workspace,
            project=project,
            board=foreign_board,
            title="X",
            created_by=user,
        )
        response = auth_client.post(
            reverse("task-move", args=[foreign.pk]), {"status": TaskStatus.TODO, "after": None}
        )
        assert response.status_code == 404


class TestTaskCreation:
    def test_new_task_lands_at_the_bottom_of_its_column(
        self, auth_client: APIClient, board: Board, user: User
    ) -> None:
        make_task(board, user, "A", TaskStatus.TODO, "1024")
        response = auth_client.post(
            reverse("task-list"),
            {
                "project": str(board.project.pk),
                "board": str(board.pk),
                "title": "Neu",
                "status": TaskStatus.TODO,
            },
        )
        assert response.status_code == 201
        assert Decimal(response.data["order"]) == Decimal("2048")
        assert column_titles(board, TaskStatus.TODO) == ["A", "Neu"]

    def test_board_must_belong_to_the_project(
        self, auth_client: APIClient, board: Board, workspace: Workspace
    ) -> None:
        other_client = Client.objects.create(workspace=workspace, name="Andere")
        other_project = Project.objects.create(
            workspace=workspace, client=other_client, name="Anderes Projekt"
        )
        response = auth_client.post(
            reverse("task-list"),
            {
                "project": str(other_project.pk),
                "board": str(board.pk),  # board of a different project
                "title": "Kaputt",
            },
        )
        assert response.status_code == 400

    def test_completing_a_task_writes_a_client_activity(
        self, auth_client: APIClient, board: Board, user: User
    ) -> None:
        from apps.crm.models import ActivityType, ClientActivity

        task = make_task(board, user, "Fertigmachen", TaskStatus.IN_PROGRESS, "1024")
        auth_client.patch(reverse("task-detail", args=[task.pk]), {"status": TaskStatus.DONE})
        assert ClientActivity.objects.filter(
            client=board.project.client, event_type=ActivityType.TASK_COMPLETED
        ).exists()
