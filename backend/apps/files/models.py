"""File metadata. Binaries live in object storage, never in PostgreSQL.

The DB holds metadata + a storage key; the bytes are fetched via short-lived
presigned URLs. Type and size are validated server-side (an extension is a
claim, not a fact).
"""

from __future__ import annotations

from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel, WorkspaceScopedModel


def upload_to(instance: StoredFile, filename: str) -> str:
    """Namespace uploads by workspace so a bucket listing is tenant-partitioned.

    Uses ``posixpath`` explicitly: object-storage keys use forward slashes, and
    the default ``os.path.join`` would inject a backslash on a Windows host.
    """
    import posixpath

    safe = posixpath.basename(filename.replace("\\", "/"))
    return posixpath.join("workspaces", str(instance.workspace_id), "files", str(instance.pk), safe)


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
    # max_length well above the default 100: the key is
    # workspaces/<uuid>/files/<uuid>/<filename> (~110 chars before the name).
    # Too small a limit makes get_available_name loop and raise.
    storage = models.FileField(upload_to=upload_to, blank=True, max_length=500)
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


@receiver(post_delete, sender=StoredFile)
def delete_stored_blob(sender: type[StoredFile], instance: StoredFile, **kwargs: object) -> None:
    """Remove object-storage bytes for direct and cascading database deletes."""
    del sender, kwargs
    if instance.storage:
        instance.storage.delete(save=False)
