"""File metadata. Binaries live in object storage, never in PostgreSQL.

The DB holds metadata + a storage key; the bytes are fetched via short-lived
presigned URLs. Type and size are validated server-side (an extension is a
claim, not a fact).
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel, WorkspaceScopedModel


def upload_to(instance: StoredFile, filename: str) -> str:
    """Namespace uploads by workspace so a bucket listing is tenant-partitioned."""
    return f"workspaces/{instance.workspace_id}/files/{instance.pk}/{filename}"


class StoredFile(WorkspaceScopedModel, BaseModel):
    # Optional owners — a file can hang off any of these, or none.
    client = models.ForeignKey(
        "crm.Client", on_delete=models.CASCADE, null=True, blank=True, related_name="files"
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="files"
    )
    task = models.ForeignKey(
        "projects.Task", on_delete=models.CASCADE, null=True, blank=True, related_name="files"
    )

    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    storage = models.FileField(upload_to=upload_to, blank=True)
    checksum = models.CharField(max_length=64, blank=True, help_text=_("sha256, for dedupe."))
    description = models.CharField(max_length=300, blank=True)
    uploaded_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="uploaded_files"
    )
    # System-generated files (e.g. invoice PDFs synced from Lexware) are marked
    # so the UI can distinguish them from user uploads.
    is_generated = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"]),
            models.Index(fields=["client", "-created_at"]),
        ]

    def __str__(self) -> str:
        return self.filename
