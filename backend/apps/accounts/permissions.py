"""Workspace resolution and DRF permission classes.

Every authorisation decision is made server-side from the session user and the
resolved workspace membership. The client may *ask* for a workspace via the
``X-Workspace-ID`` header, but the header is only ever used to look up a
membership row — it never itself grants access.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Final, cast

from rest_framework import permissions

from apps.accounts.models import ROLE_RANK, Workspace, WorkspaceMembership, WorkspaceRole

if TYPE_CHECKING:
    # Imported lazily: DRF resolves DEFAULT_PERMISSION_CLASSES while
    # rest_framework.views is still initialising, so importing APIView (or
    # Request, which pulls in views) at module scope is a circular import.
    from rest_framework.request import Request
    from rest_framework.views import APIView

WORKSPACE_HEADER = "X-Workspace-ID"

_UNSET: Final = object()

SAFE_METHODS = permissions.SAFE_METHODS


def resolve_membership(request: Request) -> WorkspaceMembership | None:
    """Resolve and cache the active membership for this request.

    Resolution order:
      1. ``X-Workspace-ID`` header — validated against the user's memberships.
      2. The user's default membership.
      3. Their only membership, if they have exactly one.

    Returns None when the user is anonymous, or when the requested workspace
    exists but the user is not a member of it. Callers must treat None as "no
    access" — never as "fall back to some workspace".
    """
    cached = getattr(request, "_coreflow_membership", _UNSET)
    if cached is not _UNSET:
        # None is a real, meaningful cached value ("resolved, and there is no
        # access") — so a sentinel is needed rather than a falsy check, which
        # would re-run the queries on every permission call for anonymous users.
        return cast("WorkspaceMembership | None", cached)

    membership: WorkspaceMembership | None = None
    user = getattr(request, "user", None)

    if user is not None and user.is_authenticated:
        base_qs = WorkspaceMembership.objects.select_related("workspace", "user").filter(
            user=user, is_active=True, workspace__is_active=True
        )
        raw_header = request.headers.get(WORKSPACE_HEADER, "").strip()

        if raw_header:
            try:
                workspace_id = uuid.UUID(raw_header)
            except ValueError:
                membership = None  # Malformed header: deny, don't fall back.
            else:
                membership = base_qs.filter(workspace_id=workspace_id).first()
        else:
            membership = base_qs.filter(is_default=True).first()
            if membership is None:
                candidates = list(base_qs[:2])
                if len(candidates) == 1:
                    membership = candidates[0]

    request._coreflow_membership = membership  # type: ignore[attr-defined]
    request._coreflow_workspace = membership.workspace if membership else None  # type: ignore[attr-defined]
    return membership


def resolve_workspace(request: Request) -> Workspace | None:
    """Return the active workspace for this request, or None."""
    membership = resolve_membership(request)
    return membership.workspace if membership else None


class IsWorkspaceMember(permissions.BasePermission):
    """Default permission: authenticated and a member of the active workspace.

    Read-only members are allowed through here and blocked on writes by
    :class:`IsWorkspaceMemberOrReadOnly`, which is what mutating viewsets use.
    """

    message = "You are not a member of this workspace."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return resolve_membership(request) is not None

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        workspace = resolve_workspace(request)
        if workspace is None:
            return False
        obj_workspace_id = getattr(obj, "workspace_id", None)
        if obj_workspace_id is None:
            return True  # Not a workspace-scoped object; view-level check applies.
        return bool(obj_workspace_id == workspace.pk)


class RequireRole(permissions.BasePermission):
    """Base for "at least role X" checks. Subclasses set ``required_role``."""

    required_role: str = WorkspaceRole.MEMBER
    message = "Your role does not permit this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        membership = resolve_membership(request)
        if membership is None:
            return False
        return membership.rank >= ROLE_RANK[self.required_role]

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        if not self.has_permission(request, view):
            return False
        workspace = resolve_workspace(request)
        obj_workspace_id = getattr(obj, "workspace_id", None)
        if obj_workspace_id is None or workspace is None:
            return True
        return bool(obj_workspace_id == workspace.pk)


class IsWorkspaceOwner(RequireRole):
    required_role = WorkspaceRole.OWNER
    message = "Only the workspace owner may perform this action."


class IsWorkspaceAdmin(RequireRole):
    required_role = WorkspaceRole.ADMIN
    message = "Admin rights are required for this action."


class IsWorkspaceMemberOrReadOnly(permissions.BasePermission):
    """Read for any member; write requires MEMBER or above (i.e. not read-only)."""

    message = "Your role is read-only in this workspace."

    def has_permission(self, request: Request, view: APIView) -> bool:
        membership = resolve_membership(request)
        if membership is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        return membership.rank >= ROLE_RANK[WorkspaceRole.MEMBER]

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        if not self.has_permission(request, view):
            return False
        workspace = resolve_workspace(request)
        obj_workspace_id = getattr(obj, "workspace_id", None)
        if obj_workspace_id is None or workspace is None:
            return True
        return bool(obj_workspace_id == workspace.pk)


class IsAdminOrReadOnly(permissions.BasePermission):
    """Read for any member; write requires ADMIN. Used for settings endpoints."""

    message = "Admin rights are required to change this setting."

    def has_permission(self, request: Request, view: APIView) -> bool:
        membership = resolve_membership(request)
        if membership is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        return membership.rank >= ROLE_RANK[WorkspaceRole.ADMIN]
