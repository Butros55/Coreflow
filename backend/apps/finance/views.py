"""Finance API: dashboard, reserve forecast, scenarios, tax profile."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminOrReadOnly, IsWorkspaceMember
from apps.core.api import WorkspaceScopedViewSet
from apps.core.pagination import DefaultPagination
from apps.finance.models import ReserveSnapshot, ReserveTransfer, TaxProfile
from apps.finance.serializers import (
    ReserveSnapshotSerializer,
    ReserveTransferSerializer,
    TaxProfileSerializer,
)
from apps.finance.services import (
    business_report,
    compute_kpis,
    compute_reserve,
    create_snapshot,
    revenue_breakdown,
)


class FinanceDashboardView(APIView):
    """Aggregated finance KPIs + revenue breakdown for the current year."""

    permission_classes = [IsWorkspaceMember]

    def get(self, request: Request) -> Response:
        from apps.accounts.permissions import resolve_workspace

        workspace = resolve_workspace(request)
        if workspace is None:
            return Response({"detail": "Kein Workspace."}, status=http_status.HTTP_403_FORBIDDEN)
        today = timezone.localdate()
        return Response(
            {
                "kpis": compute_kpis(workspace, today).as_dict(),
                "breakdown": revenue_breakdown(workspace, today.year),
                "year": today.year,
            }
        )


class BusinessReportView(APIView):
    """The full internal report: monthly series, rates, clients, projects."""

    permission_classes = [IsWorkspaceMember]

    def get(self, request: Request) -> Response:
        from apps.accounts.permissions import resolve_workspace

        workspace = resolve_workspace(request)
        if workspace is None:
            return Response({"detail": "Kein Workspace."}, status=http_status.HTTP_403_FORBIDDEN)
        return Response(business_report(workspace))


class ReserveView(APIView):
    """The tax/reserve forecast, with a transparent step-by-step trace."""

    permission_classes = [IsWorkspaceMember]

    def get(self, request: Request) -> Response:
        from apps.accounts.permissions import resolve_workspace

        workspace = resolve_workspace(request)
        if workspace is None:
            return Response({"detail": "Kein Workspace."}, status=http_status.HTTP_403_FORBIDDEN)
        year = int(request.query_params.get("year", timezone.localdate().year))
        return Response(compute_reserve(workspace, year))

    def post(self, request: Request) -> Response:
        """Scenario: recompute the reserve for an overridden annual profit."""
        from apps.accounts.permissions import resolve_workspace

        workspace = resolve_workspace(request)
        if workspace is None:
            return Response({"detail": "Kein Workspace."}, status=http_status.HTTP_403_FORBIDDEN)
        year = int(request.data.get("year", timezone.localdate().year))
        raw_profit = request.data.get("annual_profit")
        profit: Decimal | None = None
        if raw_profit is not None:
            try:
                profit = Decimal(str(raw_profit))
            except (InvalidOperation, ValueError):
                return Response(
                    {"error": {"code": "invalid_profit", "message": "Ungültiger Gewinnwert."}},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
        return Response(compute_reserve(workspace, year, scenario_annual_profit=profit))


class TaxProfileViewSet(WorkspaceScopedViewSet):
    queryset = TaxProfile.objects.all()
    serializer_class = TaxProfileSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = {"tax_year": ["exact"]}
    ordering = ["-tax_year"]

    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request: Request) -> Response:
        """The profile for the current year, creating a default if absent."""
        workspace = self.get_workspace()
        assert workspace is not None
        year = timezone.localdate().year
        profile, _ = TaxProfile.objects.get_or_create(
            workspace=workspace,
            tax_year=year,
            defaults={"small_business": workspace.small_business},
        )
        return Response(self.get_serializer(profile).data)


class ReserveTransferViewSet(WorkspaceScopedViewSet):
    """The reserve ledger: dated bookings that make up the current reserve.

    Write access is admin-only, like the tax profile — this is money
    management, not day-to-day work.
    """

    queryset = ReserveTransfer.objects.all()
    serializer_class = ReserveTransferSerializer
    permission_classes = [IsAdminOrReadOnly]
    filterset_fields = {"transfer_date": ["gte", "lte"]}
    ordering = ["-transfer_date", "-created_at"]
    http_method_names = ["get", "post", "delete", "head", "options"]


class ReserveSnapshotViewSet(viewsets.ReadOnlyModelViewSet[ReserveSnapshot]):
    serializer_class = ReserveSnapshotSerializer
    permission_classes = [IsWorkspaceMember]
    pagination_class = DefaultPagination
    ordering = ["-snapshot_date"]

    def get_queryset(self) -> Any:
        from apps.accounts.permissions import resolve_workspace

        workspace = resolve_workspace(self.request)
        if workspace is None:
            return ReserveSnapshot.objects.none()
        return ReserveSnapshot.objects.filter(workspace=workspace).order_by("-snapshot_date")

    @action(detail=False, methods=["post"], url_path="capture")
    def capture(self, request: Request) -> Response:
        """Take a snapshot now (also runs monthly via Celery Beat)."""
        from apps.accounts.permissions import resolve_workspace

        workspace = resolve_workspace(request)
        if workspace is None:
            return Response({"detail": "Kein Workspace."}, status=http_status.HTTP_403_FORBIDDEN)
        try:
            snapshot = create_snapshot(workspace)
        except ValueError as exc:
            return Response(
                {"error": {"code": "no_ruleset", "message": str(exc)}},
                status=http_status.HTTP_409_CONFLICT,
            )
        return Response(self.get_serializer(snapshot).data, status=http_status.HTTP_201_CREATED)
