"""File API: upload (validated), list, download, delete."""

from __future__ import annotations

from typing import Any

from django.http import FileResponse, Http404
from rest_framework import status as http_status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.utils import require_user
from apps.core.api import WorkspaceScopedViewSet
from apps.files.models import StoredFile
from apps.files.serializers import (
    FileUploadSerializer,
    StoredFileSerializer,
    compute_checksum,
)


class StoredFileViewSet(WorkspaceScopedViewSet):
    queryset = StoredFile.objects.select_related("uploaded_by", "client", "project")
    serializer_class = StoredFileSerializer
    parser_classes = [MultiPartParser, FormParser]
    filterset_fields = {"client": ["exact"], "project": ["exact"], "task": ["exact"]}
    search_fields = ["filename", "description"]
    ordering = ["-created_at"]
    # Upload replaces the default create; no PATCH of binary content.
    http_method_names = ["get", "post", "delete", "head", "options"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        upload = data["file"]
        workspace = self.get_workspace()
        assert workspace is not None

        # Resolve owners workspace-scoped so a foreign id cannot attach a file.
        client = self._resolve("crm.Client", data.get("client"), workspace)
        project = self._resolve("projects.Project", data.get("project"), workspace)
        task = self._resolve("projects.Task", data.get("task"), workspace)

        stored = StoredFile(
            workspace=workspace,
            client=client,
            project=project,
            task=task,
            filename=upload.name[:255],
            content_type=getattr(upload, "content_type", "") or "application/octet-stream",
            size_bytes=upload.size,
            description=data.get("description", ""),
            uploaded_by=require_user(request),
            checksum=compute_checksum(upload),
        )
        # UUID pk exists at instantiation (default=uuid4), so upload_to can build
        # the key immediately. Assign the field and save once; the FileField's
        # pre_save writes the blob via the storage backend.
        stored.storage = upload
        stored.save()

        return Response(
            StoredFileSerializer(stored, context=self.get_serializer_context()).data,
            status=http_status.HTTP_201_CREATED,
        )

    @staticmethod
    def _resolve(label: str, value: Any, workspace: Any) -> Any:
        if not value:
            return None
        from django.apps import apps

        model = apps.get_model(label)
        return model.objects.filter(workspace=workspace, pk=value).first()

    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> Any:
        """Stream the file. In production this could 302 to a presigned URL."""
        stored = self.get_object()
        if not stored.storage:
            raise Http404
        response = FileResponse(
            stored.storage.open("rb"),
            as_attachment=True,
            filename=stored.filename,
        )
        return response

    def perform_destroy(self, instance: StoredFile) -> None:
        # The post_delete receiver removes the blob for this direct delete and
        # for cascades triggered by deleting a client, project or task.
        instance.delete()
