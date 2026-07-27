"""File serializers with server-side type/size validation."""

from __future__ import annotations

import hashlib
from typing import Any

from django.conf import settings
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.core.api import WorkspaceScopedSerializer
from apps.files.models import StoredFile


class StoredFileSerializer(WorkspaceScopedSerializer):
    uploaded_by = UserSerializer(read_only=True)
    download_url = serializers.SerializerMethodField()
    size_display = serializers.SerializerMethodField()

    class Meta:
        model = StoredFile
        fields = [
            "id",
            "client",
            "project",
            "task",
            "filename",
            "content_type",
            "size_bytes",
            "size_display",
            "description",
            "uploaded_by",
            "is_generated",
            "download_url",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "content_type",
            "size_bytes",
            "uploaded_by",
            "is_generated",
            "created_at",
        ]

    def get_download_url(self, obj: StoredFile) -> str | None:
        if not obj.storage:
            return None
        # Presigned/short-lived URL from the storage backend (S3) or a local
        # media URL in dev.
        try:
            return obj.storage.url
        except Exception:
            return None

    def get_size_display(self, obj: StoredFile) -> str:
        size = float(obj.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"


class FileUploadSerializer(serializers.Serializer[dict[str, Any]]):
    """Validates an uploaded file against the server-side allow-list and size cap.

    An extension is a claim; the size and extension checks here are the real
    gate (client-side validation is a convenience, not security).
    """

    file = serializers.FileField()
    client = serializers.UUIDField(required=False, allow_null=True)
    project = serializers.UUIDField(required=False, allow_null=True)
    task = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=300, default=""
    )

    def validate_file(self, value: Any) -> Any:
        max_bytes = settings.FILE_UPLOAD_MAX_BYTES
        if value.size > max_bytes:
            raise serializers.ValidationError(
                f"Datei zu groß (max. {max_bytes // (1024 * 1024)} MB)."
            )
        extension = value.name.rsplit(".", 1)[-1].lower() if "." in value.name else ""
        allowed = settings.FILE_UPLOAD_ALLOWED_EXTENSIONS
        if extension not in allowed:
            raise serializers.ValidationError(f"Dateityp „.{extension}“ ist nicht erlaubt.")
        return value


def compute_checksum(uploaded_file: Any) -> str:
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()
