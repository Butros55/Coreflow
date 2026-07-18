"""Authentication and workspace endpoints."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.db import transaction
from django.db.models import QuerySet
from django.middleware.csrf import get_token
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import ROLE_RANK, Workspace, WorkspaceMembership, WorkspaceRole
from apps.accounts.permissions import (
    IsWorkspaceAdmin,
    resolve_membership,
    resolve_workspace,
)
from apps.accounts.serializers import (
    LoginSerializer,
    MembershipSerializer,
    PasswordChangeSerializer,
    SessionSerializer,
    UserSerializer,
    WorkspaceSerializer,
    WorkspaceSummarySerializer,
)
from apps.accounts.utils import require_user
from apps.core.audit import record_audit, record_audit_after_rollback
from apps.core.logging import get_logger

logger = get_logger("accounts.views")


def _permission_map(role: str) -> dict[str, bool]:
    """Capability flags the UI uses to hide controls.

    This is a *hint for rendering only*. Every one of these is independently
    enforced server-side; hiding a button is not access control.
    """
    rank = ROLE_RANK.get(role, 0)
    return {
        "can_read": rank >= ROLE_RANK[WorkspaceRole.READONLY],
        "can_write": rank >= ROLE_RANK[WorkspaceRole.MEMBER],
        "can_manage_settings": rank >= ROLE_RANK[WorkspaceRole.ADMIN],
        "can_manage_members": rank >= ROLE_RANK[WorkspaceRole.ADMIN],
        "can_manage_integrations": rank >= ROLE_RANK[WorkspaceRole.ADMIN],
        "can_delete_workspace": rank >= ROLE_RANK[WorkspaceRole.OWNER],
    }


class CsrfView(APIView):
    """Hand the SPA a CSRF cookie before it attempts a login POST."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    @extend_schema(
        summary="Bootstrap CSRF cookie",
        description="Sets the CSRF cookie and returns the token. Call before login.",
        responses={200: OpenApiResponse(description="CSRF token issued")},
        auth=[],
    )
    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request)})


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"

    @extend_schema(
        summary="Log in",
        request=LoginSerializer,
        responses={200: SessionSerializer, 400: OpenApiResponse(description="Invalid credentials")},
        auth=[],
    )
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data, context={"request": request})
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            # Deferred write: the error response rolls this request's
            # transaction back, and the audit row must survive it.
            record_audit_after_rollback(
                request,
                "auth.login_failed",
                email=str(request.data.get("email", ""))[:100],
            )
            raise
        user = serializer.validated_data["user"]

        django_login(request, user)
        # New session id on privilege change — defeats session fixation.
        request.session.cycle_key()

        record_audit(request, "auth.login", actor=user)
        logger.info("login_succeeded", user_id=str(user.pk))
        return Response(_build_session_payload(request))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Log out", request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        user_id = str(request.user.pk)
        record_audit(request, "auth.logout")
        django_logout(request)
        logger.info("logout", user_id=user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionView(APIView):
    """Who am I, which workspace am I in, and what may I do."""

    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Current session", responses={200: SessionSerializer})
    def get(self, request: Request) -> Response:
        return Response(_build_session_payload(request))


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Change password", request=PasswordChangeSerializer, responses={204: None}
    )
    def post(self, request: Request) -> Response:
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = require_user(request)
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        # Keep this session alive; Django would otherwise invalidate it.
        from django.contrib.auth import update_session_auth_hash

        update_session_auth_hash(request, user)

        record_audit(request, "auth.password_changed")
        logger.info("password_changed", user_id=str(user.pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Get current user", responses={200: UserSerializer})
    def get(self, request: Request) -> Response:
        return Response(UserSerializer(require_user(request)).data)

    @extend_schema(
        summary="Update current user profile",
        request=UserSerializer,
        responses={200: UserSerializer},
    )
    def patch(self, request: Request) -> Response:
        serializer = UserSerializer(require_user(request), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


def _build_session_payload(request: Request) -> dict[str, Any]:
    user = require_user(request)
    memberships = list(
        WorkspaceMembership.objects.select_related("workspace")
        .filter(user=user, is_active=True, workspace__is_active=True)
        .order_by("workspace__name")
    )
    role_map = {m.workspace_id: m.role for m in memberships}
    workspaces = [m.workspace for m in memberships]

    active = resolve_membership(request)

    return {
        "user": UserSerializer(user).data,
        "workspace": WorkspaceSerializer(active.workspace).data if active else None,
        "workspaces": WorkspaceSummarySerializer(
            workspaces, many=True, context={"role_map": role_map}
        ).data,
        "role": active.role if active else None,
        "permissions": _permission_map(active.role) if active else {},
    }


class WorkspaceViewSet(viewsets.ModelViewSet[Workspace]):
    """Workspaces the current user belongs to.

    Creation is deliberately absent: workspaces are provisioned by seeding or by
    an owner-level flow, not by any authenticated caller.
    """

    serializer_class = WorkspaceSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_permissions(self) -> list[Any]:
        if self.request.method in ("PATCH", "PUT", "DELETE"):
            return [IsWorkspaceAdmin()]
        from apps.accounts.permissions import IsWorkspaceMember

        return [IsWorkspaceMember()]

    def get_queryset(self) -> QuerySet[Workspace]:
        # Scoped to membership: an ID from another workspace 404s rather than resolving.
        return Workspace.objects.filter(
            memberships__user=require_user(self.request),
            memberships__is_active=True,
            is_active=True,
        ).distinct()

    def perform_update(self, serializer: Any) -> None:
        workspace = serializer.save()
        record_audit(
            self.request,
            "workspace.updated",
            workspace=workspace,
            target=workspace,
            fields=sorted(serializer.validated_data.keys()),
        )

    @extend_schema(
        summary="Switch the default workspace", request=None, responses={200: SessionSerializer}
    )
    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request: Request, pk: str | None = None) -> Response:
        workspace = self.get_object()
        user = require_user(request)
        with transaction.atomic():
            WorkspaceMembership.objects.filter(user=user, is_default=True).update(is_default=False)
            WorkspaceMembership.objects.filter(user=user, workspace=workspace).update(
                is_default=True
            )
        # The cached membership predates the switch.
        if hasattr(request, "_coreflow_membership"):
            del request._coreflow_membership
        return Response(_build_session_payload(request))

    @extend_schema(
        summary="List members of the active workspace",
        responses={200: MembershipSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def members(self, request: Request, pk: str | None = None) -> Response:
        workspace = self.get_object()
        memberships = (
            WorkspaceMembership.objects.select_related("user")
            .filter(workspace=workspace, is_active=True)
            .order_by("user__email")
        )
        return Response(MembershipSerializer(memberships, many=True).data)


class MembershipViewSet(viewsets.ModelViewSet[WorkspaceMembership]):
    """Manage who belongs to the active workspace. Admin+ only."""

    serializer_class = MembershipSerializer
    permission_classes = [IsWorkspaceAdmin]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self) -> QuerySet[WorkspaceMembership]:
        workspace = resolve_workspace(self.request)
        if workspace is None:
            return WorkspaceMembership.objects.none()
        return (
            WorkspaceMembership.objects.select_related("user", "workspace")
            .filter(workspace=workspace)
            .order_by("user__email")
        )

    def perform_update(self, serializer: Any) -> None:
        membership: WorkspaceMembership = self.get_object()
        new_role = serializer.validated_data.get("role", membership.role)
        actor = resolve_membership(self.request)

        # Guard rails that a role field alone cannot express:
        # 1. Only an owner may mint another owner (admins must not self-promote).
        if new_role == WorkspaceRole.OWNER and (actor is None or actor.role != WorkspaceRole.OWNER):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(_("Only the workspace owner may grant owner rights."))

        # 2. Never leave a workspace ownerless.
        if membership.role == WorkspaceRole.OWNER and new_role != WorkspaceRole.OWNER:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"role": _("Transfer ownership to another member before demoting the owner.")}
            )
        old_role = membership.role
        serializer.save()
        record_audit(
            self.request,
            "member.updated",
            workspace=membership.workspace,
            target=membership,
            summary=f"{membership.user.email}: {old_role} → {new_role}",
        )

    def perform_destroy(self, instance: WorkspaceMembership) -> None:
        if instance.role == WorkspaceRole.OWNER:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"detail": _("The workspace owner cannot be removed. Transfer ownership first.")}
            )
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        record_audit(
            self.request,
            "member.removed",
            workspace=instance.workspace,
            target=instance,
            summary=instance.user.email,
        )
