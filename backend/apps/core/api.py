"""Shared API building blocks for workspace-scoped resources.

Every domain viewset inherits :class:`WorkspaceScopedViewSet`, which is where the
two tenancy guarantees live:

* ``get_queryset`` filters by the resolved workspace, so an object ID from
  another workspace 404s instead of resolving (IDOR defence at the view layer).
* ``perform_create`` stamps the workspace server-side; the client cannot choose
  one.

:class:`WorkspaceScopedSerializer` closes the third hole: related fields. A
``PrimaryKeyRelatedField`` with an unfiltered queryset would happily accept a
foreign workspace's project UUID on a task. The mixin narrows every related
queryset whose model is workspace-scoped, so cross-tenant references fail
validation with a 400 rather than silently linking tenants together.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers, viewsets

from apps.accounts.models import User, Workspace
from apps.accounts.permissions import IsWorkspaceMemberOrReadOnly, resolve_workspace


def workspace_users_qs(workspace: Workspace | None) -> QuerySet[User]:
    """Users who may be referenced (assignee, lead, …) in this workspace."""
    if workspace is None:
        return User.objects.none()
    return User.objects.filter(
        memberships__workspace=workspace, memberships__is_active=True
    ).distinct()


class WorkspaceScopedSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    """ModelSerializer that narrows related querysets to the active workspace."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        workspace = resolve_workspace(request) if request is not None else None

        for field in self.fields.values():
            relation: Any = (
                field.child_relation if isinstance(field, serializers.ManyRelatedField) else field
            )
            queryset = getattr(relation, "queryset", None)
            if queryset is None:
                continue
            model = queryset.model
            if model is User:
                relation.queryset = workspace_users_qs(workspace)
            elif hasattr(model, "workspace_id"):
                relation.queryset = (
                    queryset.filter(workspace=workspace)
                    if workspace is not None
                    else queryset.none()
                )


class WorkspaceScopedViewSet(viewsets.ModelViewSet):  # type: ignore[type-arg]
    """CRUD base for workspace-scoped models.

    Subclasses set ``queryset`` and ``serializer_class`` as usual. Reads are open
    to every member; writes require MEMBER or above (read-only role blocked).
    """

    permission_classes = [IsWorkspaceMemberOrReadOnly]

    def get_workspace(self) -> Workspace | None:
        return resolve_workspace(self.request)

    def get_queryset(self) -> QuerySet[Any]:
        assert self.queryset is not None, "WorkspaceScopedViewSet needs a queryset"
        workspace = self.get_workspace()
        if workspace is None:
            return self.queryset.none()
        return self.queryset.filter(workspace=workspace)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:  # type: ignore[type-arg]
        serializer.save(workspace=self.get_workspace(), **self.extra_create_kwargs())

    def extra_create_kwargs(self) -> dict[str, Any]:
        """Hook for stamping server-side fields (author, created_by, …)."""
        return {}
