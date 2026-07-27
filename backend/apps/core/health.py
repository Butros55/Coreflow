"""Liveness and readiness endpoints.

The split matters for orchestration: liveness answers "is this process wedged,
should it be restarted?", readiness answers "can it serve traffic right now?".
Conflating them makes a brief database blip restart-loop the whole deployment.
"""

from __future__ import annotations

import time
from typing import Any

from django.conf import settings
from django.db import connections, transaction
from django.db.utils import OperationalError
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.logging import get_logger

logger = get_logger("core.health")

# ATOMIC_REQUESTS wraps every view in a transaction, which would make these
# probes open a database connection before their code runs — so a database
# outage would turn liveness into a 500 and restart-loop every container, and
# would pre-empt readiness' own graceful 503. Probes must be non-atomic to be
# able to report on the very dependency they check.
_non_atomic = method_decorator(transaction.non_atomic_requests, name="dispatch")


@_non_atomic
class LivenessView(APIView):
    """Liveness: the process is running. Intentionally checks no dependencies."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    @extend_schema(
        summary="Liveness probe",
        description="Returns 200 whenever the process is able to serve requests.",
        responses={200: {"type": "object", "properties": {"status": {"type": "string"}}}},
        auth=[],
    )
    def get(self, request: Request) -> Response:
        return Response({"status": "ok", "service": "coreflow-backend"})


@_non_atomic
class ReadinessView(APIView):
    """Readiness: every backing service this process needs is reachable."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    @extend_schema(
        summary="Readiness probe",
        description=(
            "Checks database and cache connectivity. Returns 503 if any dependency "
            "is unavailable, so a load balancer can route around this instance."
        ),
        auth=[],
    )
    def get(self, request: Request) -> Response:
        checks: dict[str, Any] = {}
        healthy = True

        db_ok, db_detail = self._check_database()
        checks["database"] = db_detail
        healthy &= db_ok

        cache_ok, cache_detail = self._check_cache()
        checks["cache"] = cache_detail
        healthy &= cache_ok

        checks["integrations"] = {
            "lexware": "enabled" if settings.LEXWARE_ENABLED else "disabled",
            "clockify": "enabled" if settings.CLOCKIFY_ENABLED else "disabled",
        }

        return Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def _check_database() -> tuple[bool, dict[str, Any]]:
        started = time.perf_counter()
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except OperationalError as exc:
            logger.warning("readiness_database_failed", error=str(exc))
            return False, {"status": "error", "error": "database unreachable"}
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return True, {"status": "ok", "latency_ms": latency_ms}

    @staticmethod
    def _check_cache() -> tuple[bool, dict[str, Any]]:
        from django.core.cache import cache

        started = time.perf_counter()
        try:
            cache.set("healthcheck", "ok", 10)
            value = cache.get("healthcheck")
        except Exception as exc:
            logger.warning("readiness_cache_failed", error=str(exc))
            return False, {"status": "error", "error": "cache unreachable"}
        if value != "ok":
            return False, {"status": "error", "error": "cache read-back mismatch"}
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return True, {"status": "ok", "latency_ms": latency_ms}


@_non_atomic
class VersionView(APIView):
    """Build/version metadata for support and debugging."""

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    @extend_schema(summary="Version info", auth=[])
    def get(self, request: Request) -> Response:
        return Response(
            {
                "service": "coreflow-backend",
                "version": getattr(settings, "APP_VERSION", "0.1.0"),
                "environment": settings.APP_ENV,
                "time_zone": settings.TIME_ZONE,
            }
        )
