"""Audit log: who did what, when, from where.

Security-relevant actions are recorded append-only. Entries are never updated
or deleted through the API; retention is the database backup policy. Recording
is fail-open — an audit failure is logged loudly but never breaks the request
that triggered it (a single-operator tool locking its user out over a full
disk would be the worse trade).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.logging import get_logger
from apps.core.models import BaseModel

if TYPE_CHECKING:
    from rest_framework.request import Request

logger = get_logger("core.audit")

# Dotted, greppable action names. Free-form by design: new call sites should
# not require a migration. The canonical set lives in the tests and docs.
#   auth.login / auth.login_failed / auth.logout / auth.password_changed
#   workspace.updated / member.updated / member.removed
#   invoice.sent / invoice.cancelled
#   integration.connection_tested / integration.sync_triggered
#   integration.conflict_resolved
#   privacy.client_exported / privacy.client_erased / privacy.client_deleted


class AuditLogEntry(BaseModel):
    """One recorded action. ``workspace`` is nullable: failed logins have none."""

    workspace = models.ForeignKey(
        "accounts.Workspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="audit_entries",
    )
    actor = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    summary = models.CharField(max_length=300, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("audit log entry")
        verbose_name_plural = _("audit log entries")
        indexes = [
            models.Index(fields=["workspace", "-created_at"]),
            models.Index(fields=["workspace", "action", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_id or 'anonymous'}"


def client_ip(request: Request) -> str | None:
    """Leftmost X-Forwarded-For hop (set by our own proxy) or the socket peer."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def record_audit(
    request: Request | None,
    action: str,
    *,
    workspace: Any = None,
    actor: Any = None,
    target: Any = None,
    target_type: str = "",
    target_id: str = "",
    summary: str = "",
    **metadata: Any,
) -> None:
    """Append one audit entry. Never raises.

    ``target`` may be any model instance — its class label and pk are recorded.
    ``actor`` defaults to the authenticated request user.
    """
    try:
        if target is not None:
            target_type = target_type or f"{target._meta.app_label}.{target._meta.object_name}"
            target_id = target_id or str(target.pk)
        if actor is None and request is not None:
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                actor = user
        AuditLogEntry.objects.create(
            workspace=workspace,
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=str(target_id)[:64],
            summary=summary[:300],
            metadata=metadata,
            ip_address=client_ip(request) if request is not None else None,
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:200] if request else ""),
        )
    except Exception:
        # Fail-open by design — but never silently.
        logger.exception("audit_write_failed", action=action)


def record_audit_after_rollback(request: Request, action: str, **metadata: Any) -> None:
    """Audit an action whose request transaction is about to be rolled back.

    ``ATOMIC_REQUESTS`` wraps the *view*; a 4xx raised through DRF marks that
    transaction for rollback, which would erase an audit row written inside it
    (the failed-login case). Middleware runs outside the atomic block, so the
    entry is stashed on the request and flushed post-response by
    :class:`AuditFlushMiddleware`.
    """
    # Stash on the underlying HttpRequest: DRF's Request wrapper takes the
    # setattr itself, and the middleware only ever sees the Django request.
    base_request: Any = getattr(request, "_request", request)
    pending = getattr(base_request, "_pending_audit", None)
    if pending is None:
        pending = []
        base_request._pending_audit = pending
    pending.append(
        {
            "action": action,
            "metadata": metadata,
            "ip_address": client_ip(request),
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
        }
    )


class AuditFlushMiddleware:
    """Writes deferred audit entries after the view's transaction has closed."""

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        response = self.get_response(request)
        for item in getattr(request, "_pending_audit", []):
            try:
                AuditLogEntry.objects.create(
                    workspace=None,
                    actor=None,
                    action=item["action"],
                    metadata=item["metadata"],
                    ip_address=item["ip_address"],
                    user_agent=item["user_agent"],
                )
            except Exception:
                logger.exception("audit_flush_failed", action=item["action"])
        return response
