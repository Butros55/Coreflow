"""Stored blobs are removed for direct and cascading deletes."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.accounts.models import Workspace
from apps.crm.models import Client
from apps.files.models import StoredFile
from apps.projects.models import Project

pytestmark = pytest.mark.django_db


def test_project_cascade_removes_stored_blob(workspace: Workspace) -> None:
    client = Client.objects.create(workspace=workspace, name="Kunde")
    project = Project.objects.create(workspace=workspace, client=client, name="Projekt")
    stored = StoredFile.objects.create(
        workspace=workspace,
        project=project,
        filename="anhang.pdf",
        storage="workspaces/test/files/anhang.pdf",
    )
    storage = StoredFile._meta.get_field("storage").storage

    with patch.object(storage, "delete") as delete_blob:
        project.delete()

    assert not StoredFile.objects.filter(pk=stored.pk).exists()
    delete_blob.assert_called_once_with("workspaces/test/files/anhang.pdf")
