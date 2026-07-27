"""Shared abstract base models.

Primary keys are UUIDv4 across the whole schema. That costs a little index space
versus bigserial, but it means IDs are safe to expose in URLs (no enumeration of
"how many clients do you have?"), and objects can be created client-side or
merged from an external provider without a round-trip for an ID.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from django.db import models
from django.utils import timezone

if TYPE_CHECKING:
    from apps.accounts.models import Workspace


class UUIDModel(models.Model):
    """Abstract base giving every model a UUID primary key."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    """Abstract base tracking creation and modification times (stored UTC)."""

    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimestampedModel):
    """UUID primary key + timestamps. The default base for Coreflow models."""

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet["SoftDeleteModel"]):
    def alive(self) -> SoftDeleteQuerySet:
        return self.filter(deleted_at__isnull=True)

    def dead(self) -> SoftDeleteQuerySet:
        return self.filter(deleted_at__isnull=False)

    def delete(self) -> tuple[int, dict[str, int]]:
        """Soft-delete in bulk.

        Overriding queryset.delete() keeps cascade-ish call sites from hard
        deleting rows that legal retention rules may require us to keep.
        """
        count = self.update(deleted_at=timezone.now())
        return count, {}


class SoftDeleteModel(models.Model):
    """Abstract base for records that must survive deletion for audit/retention.

    ``objects`` returns only live rows. ``all_objects`` includes soft-deleted
    rows and is what admin/export/retention code should use.
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True, editable=False)

    # Order matters: Django makes the FIRST declared manager `_default_manager`,
    # which related descriptors, dumpdata and the admin all use. `objects` must
    # therefore come first so those paths exclude soft-deleted rows by default.
    # ruff's DJ012 misreads `models.Manager()` as a field declaration and wants
    # these swapped; doing so would silently resurrect deleted rows across every
    # relation, so the rule is suppressed rather than obeyed.
    objects = SoftDeleteQuerySet.as_manager()
    all_objects = models.Manager()  # noqa: DJ012

    class Meta:
        abstract = True

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at", "updated_at"])
        return 1, {self._meta.label: 1}

    def hard_delete(self, using: str | None = None) -> tuple[int, dict[str, int]]:
        """Permanently remove the row. Only for GDPR erasure paths."""
        return super().delete(using=using)

    def restore(self) -> None:
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class WorkspaceScopedQuerySet(models.QuerySet[Any]):
    def for_workspace(self, workspace: Workspace | uuid.UUID) -> WorkspaceScopedQuerySet:
        workspace_id = workspace if isinstance(workspace, uuid.UUID) else workspace.pk
        return self.filter(workspace_id=workspace_id)


class WorkspaceScopedModel(models.Model):
    """Abstract base for tenant-scoped records.

    Every domain object hangs off a workspace. The API layer filters on this in
    ``WorkspaceScopedViewSet.get_queryset`` so that an object ID leaked or
    guessed from another workspace 404s rather than resolving (IDOR defence).
    """

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        db_index=True,
    )

    objects = WorkspaceScopedQuerySet.as_manager()

    class Meta:
        abstract = True


# Concrete models defined in sibling modules must be imported here so Django's
# app registry discovers them.
from apps.core.audit import AuditLogEntry  # noqa: E402,F401
