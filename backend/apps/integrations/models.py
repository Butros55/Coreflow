"""Provider-agnostic synchronisation infrastructure.

Four models carry every external integration:

* :class:`ExternalObjectLink` — the mapping between a local object and its remote
  counterpart, plus the hash that makes syncs idempotent.
* :class:`SyncJob` — one run of a sync, for observability and resumability.
* :class:`WebhookEvent` — inbound events, persisted *before* processing.
* :class:`SyncConflict` — divergence a human must resolve.

Deliberately provider-agnostic: adding a third provider means adding a value to
:class:`Provider` and implementing the port, not touching this schema.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel, WorkspaceScopedModel


class Provider(models.TextChoices):
    LEXWARE = "lexware", _("Lexware Office")
    CLOCKIFY = "clockify", _("Clockify")


class SyncDirection(models.TextChoices):
    INBOUND = "inbound", _("Inbound (remote → local)")
    OUTBOUND = "outbound", _("Outbound (local → remote)")
    BIDIRECTIONAL = "bidirectional", _("Bidirectional")


class SyncStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    RUNNING = "running", _("Running")
    SUCCESS = "success", _("Success")
    PARTIAL = "partial", _("Partial success")
    FAILED = "failed", _("Failed")
    SKIPPED = "skipped", _("Skipped (integration disabled)")


class WebhookProcessingStatus(models.TextChoices):
    RECEIVED = "received", _("Received")
    PROCESSING = "processing", _("Processing")
    PROCESSED = "processed", _("Processed")
    FAILED = "failed", _("Failed")
    IGNORED = "ignored", _("Ignored (not subscribed / unknown type)")
    DUPLICATE = "duplicate", _("Duplicate (already processed)")


class ConflictResolutionStatus(models.TextChoices):
    OPEN = "open", _("Open")
    RESOLVED_LOCAL = "resolved_local", _("Resolved — local version kept")
    RESOLVED_REMOTE = "resolved_remote", _("Resolved — remote version kept")
    RESOLVED_MANUAL = "resolved_manual", _("Resolved — manually merged")
    IGNORED = "ignored", _("Ignored")


def compute_sync_hash(payload: dict[str, Any]) -> str:
    """Stable hash of a remote payload, used to skip no-op writes.

    Keys are sorted and the JSON is compact so that a semantically identical
    payload always hashes the same, regardless of the provider's key ordering.
    Values are stringified via ``default=str`` because payloads contain Decimals
    and datetimes that are not natively JSON-serialisable.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ExternalObjectLink(WorkspaceScopedModel, BaseModel):
    """Maps a local object to its counterpart in an external system.

    A separate link table rather than ``lexware_id`` columns on each model: it
    keeps provider concerns out of the domain schema, allows one local object to
    link to several providers, and gives sync metadata (version, hash, deletion)
    somewhere to live without polluting business tables.

    ``local_object_id`` is an untyped UUID rather than a ``GenericForeignKey``:
    every Coreflow PK is a UUID, and the contenttypes framework's joins are not
    worth the cost for a table that is always queried by
    ``(provider, resource_type, external_id)``.
    """

    provider = models.CharField(max_length=32, choices=Provider.choices, db_index=True)
    resource_type = models.CharField(
        max_length=64,
        db_index=True,
        help_text=_("Provider-side resource, e.g. 'contact', 'invoice', 'entry'."),
    )
    local_object_type = models.CharField(
        max_length=64, help_text=_("Django label, e.g. 'crm.Client'.")
    )
    local_object_id = models.UUIDField(db_index=True)

    external_id = models.CharField(max_length=128, db_index=True)
    external_version = models.CharField(
        max_length=64,
        blank=True,
        help_text=_("Remote version/revision. Lexware uses an int; Clockify has none."),
    )
    sync_hash = models.CharField(
        max_length=80,
        blank=True,
        help_text=_("Hash of the last-synced remote payload; equal hash ⇒ skip write."),
    )
    last_synced_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_remote_modified_at = models.DateTimeField(null=True, blank=True)
    deleted_remotely = models.BooleanField(default=False, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("external object link")
        verbose_name_plural = _("external object links")
        constraints = [
            # The idempotency guarantee: one remote object maps to one local
            # object per workspace. Repeated webhooks hit this and update rather
            # than insert.
            models.UniqueConstraint(
                fields=["workspace", "provider", "resource_type", "external_id"],
                name="unique_external_object_per_workspace",
            ),
            # And the reverse: a local object links to a given provider resource once.
            models.UniqueConstraint(
                fields=["workspace", "provider", "resource_type", "local_object_id"],
                name="unique_local_object_link_per_provider",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "resource_type", "external_id"]),
            models.Index(fields=["local_object_type", "local_object_id"]),
            models.Index(fields=["provider", "deleted_remotely"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.resource_type}:{self.external_id} → {self.local_object_type}"

    def payload_changed(self, payload: dict[str, Any]) -> bool:
        """True when this payload differs from the last synced one."""
        return compute_sync_hash(payload) != self.sync_hash

    def mark_synced(self, payload: dict[str, Any], *, remote_modified_at: Any = None) -> None:
        self.sync_hash = compute_sync_hash(payload)
        self.last_synced_at = timezone.now()
        if remote_modified_at is not None:
            self.last_remote_modified_at = remote_modified_at
        self.save(
            update_fields=["sync_hash", "last_synced_at", "last_remote_modified_at", "updated_at"]
        )


class SyncJob(WorkspaceScopedModel, BaseModel):
    """One synchronisation run: what ran, how it went, and where it stopped."""

    provider = models.CharField(max_length=32, choices=Provider.choices, db_index=True)
    resource_type = models.CharField(max_length=64, db_index=True)
    direction = models.CharField(
        max_length=16, choices=SyncDirection.choices, default=SyncDirection.INBOUND
    )
    status = models.CharField(
        max_length=16, choices=SyncStatus.choices, default=SyncStatus.PENDING, db_index=True
    )

    trigger = models.CharField(
        max_length=32,
        default="scheduled",
        help_text=_("scheduled | manual | webhook | connect"),
    )
    is_full_sync = models.BooleanField(default=False)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    records_processed = models.PositiveIntegerField(default=0)
    records_created = models.PositiveIntegerField(default=0)
    records_updated = models.PositiveIntegerField(default=0)
    records_skipped = models.PositiveIntegerField(default=0)
    records_failed = models.PositiveIntegerField(default=0)

    error_summary = models.TextField(blank=True)
    # Where a windowed full sync got to, so a failure resumes instead of restarting.
    cursor = models.JSONField(
        default=dict, blank=True, help_text=_("Resume point, e.g. {'window_end': '2024-03-01'}.")
    )
    triggered_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="sync_jobs"
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("sync job")
        verbose_name_plural = _("sync jobs")
        indexes = [
            models.Index(fields=["provider", "resource_type", "-created_at"]),
            models.Index(fields=["provider", "status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.resource_type} [{self.status}]"

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    def mark_running(self) -> None:
        self.status = SyncStatus.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at", "updated_at"])

    def mark_finished(self, status: str, error_summary: str = "") -> None:
        self.status = status
        self.finished_at = timezone.now()
        # Truncated: error text can be an unbounded provider response.
        self.error_summary = error_summary[:5000]
        self.save(update_fields=["status", "finished_at", "error_summary", "updated_at"])


class WebhookEvent(WorkspaceScopedModel, BaseModel):
    """An inbound webhook, persisted before any processing.

    Lexware sends **pointers, not data** (``{organizationId, eventType,
    resourceId, eventDate}``); Clockify sends the full entity JSON with the
    event name in a header. Processing still always means "fetch the resource,
    then reconcile" — a webhook body may be stale by the time it is processed —
    so the payload here is evidence for debugging rather than a source of truth.

    Persist-then-ack is not optional: Lexware's read timeout is 5000 ms and a
    persistent failure to respond causes it to **delete the subscription**.
    """

    provider = models.CharField(max_length=32, choices=Provider.choices, db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    external_resource_id = models.CharField(max_length=128, blank=True, db_index=True)

    payload = models.JSONField(default=dict)
    headers = models.JSONField(
        default=dict, blank=True, help_text=_("Selected headers, credentials scrubbed.")
    )

    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_status = models.CharField(
        max_length=16,
        choices=WebhookProcessingStatus.choices,
        default=WebhookProcessingStatus.RECEIVED,
        db_index=True,
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(blank=True)

    # Provider-side event identity, used for deduplication. For Lexware this is
    # a digest of (eventType, resourceId, eventDate); for Clockify
    # (event type, entity id, payload digest). Neither provider guarantees
    # exactly-once delivery, so we enforce it ourselves.
    dedupe_key = models.CharField(max_length=128, blank=True, db_index=True)
    signature_verified = models.BooleanField(
        default=False, help_text=_("Lexware: RSA-SHA512 verified. Clockify: signature matched.")
    )

    class Meta:
        ordering = ["-received_at"]
        verbose_name = _("webhook event")
        verbose_name_plural = _("webhook events")
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "dedupe_key"],
                condition=models.Q(dedupe_key__gt=""),
                name="unique_webhook_dedupe_key",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "processing_status", "received_at"]),
            models.Index(fields=["provider", "event_type", "-received_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_type}:{self.external_resource_id}"

    def mark_processed(self) -> None:
        self.processing_status = WebhookProcessingStatus.PROCESSED
        self.processed_at = timezone.now()
        self.save(update_fields=["processing_status", "processed_at", "updated_at"])

    def mark_failed(self, error: str) -> None:
        self.processing_status = WebhookProcessingStatus.FAILED
        self.processed_at = timezone.now()
        self.error_message = error[:5000]
        self.retry_count += 1
        self.save(
            update_fields=[
                "processing_status",
                "processed_at",
                "error_message",
                "retry_count",
                "updated_at",
            ]
        )


class SyncConflict(WorkspaceScopedModel, BaseModel):
    """A divergence between local and remote that we refuse to resolve silently.

    Raised when local and remote both changed since the last sync, when a remote
    write is rejected for a structural reason (e.g. a Lexware contact with
    multi-entry lists), or when a linked remote object disappeared. Both
    snapshots are stored so the user can see exactly what differs.
    """

    provider = models.CharField(max_length=32, choices=Provider.choices, db_index=True)
    resource_type = models.CharField(max_length=64, db_index=True)

    local_object_type = models.CharField(max_length=64)
    local_object_id = models.UUIDField(null=True, blank=True, db_index=True)
    external_id = models.CharField(max_length=128, blank=True, db_index=True)

    local_snapshot = models.JSONField(default=dict)
    remote_snapshot = models.JSONField(default=dict)

    reason = models.CharField(
        max_length=64,
        default="concurrent_modification",
        help_text=_(
            "concurrent_modification | version_conflict | remote_deleted | "
            "unwritable_remote | ambiguous_match"
        ),
    )
    detected_at = models.DateTimeField(default=timezone.now, db_index=True)
    resolution_status = models.CharField(
        max_length=24,
        choices=ConflictResolutionStatus.choices,
        default=ConflictResolutionStatus.OPEN,
        db_index=True,
    )
    resolution = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_conflicts",
    )
    sync_job = models.ForeignKey(
        SyncJob, null=True, blank=True, on_delete=models.SET_NULL, related_name="conflicts"
    )

    class Meta:
        ordering = ["-detected_at"]
        verbose_name = _("sync conflict")
        verbose_name_plural = _("sync conflicts")
        indexes = [
            models.Index(fields=["provider", "resolution_status", "-detected_at"]),
        ]

    def __str__(self) -> str:
        return f"conflict {self.provider}:{self.resource_type}:{self.external_id}"

    @property
    def is_open(self) -> bool:
        return self.resolution_status == ConflictResolutionStatus.OPEN


class ProviderProfile(WorkspaceScopedModel, BaseModel):
    """Cached remote account/profile info, refreshed on connect and periodic sync.

    Lexware's profile is load-bearing: ``organizationId`` authenticates inbound
    webhooks and ``taxType``/``smallBusiness`` drive invoice defaults. Caching it
    means invoice creation does not depend on a live call — and, importantly,
    means we can *refuse* to build an invoice when it has never been fetched
    rather than guessing a tax type.
    """

    provider = models.CharField(max_length=32, choices=Provider.choices, db_index=True)

    external_organization_id = models.CharField(max_length=128, blank=True, db_index=True)
    connection_id = models.CharField(
        max_length=128,
        blank=True,
        help_text=_("Lexware connectionId — the resourceId carried by token.revoked events."),
    )
    company_name = models.CharField(max_length=255, blank=True)

    # Lexware profile.taxType: net | gross | vatfree. Authoritative default for
    # invoice taxConditions.taxType — never hardcoded (see docs/integrations/lexware.md §4.5).
    tax_type = models.CharField(max_length=32, blank=True)
    small_business = models.BooleanField(default=False)
    # Stored verbatim and displayed, never branched on: the enum is undocumented.
    subscription_status = models.CharField(max_length=64, blank=True)

    raw_profile = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("provider profile")
        verbose_name_plural = _("provider profiles")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "provider"], name="unique_provider_profile_per_workspace"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider} profile: {self.company_name or self.external_organization_id}"
