"""Core (infrastructure) URLs."""

from django.urls import path

from apps.core.health import LivenessView, ReadinessView, VersionView

app_name = "core"

urlpatterns = [
    path("healthz", LivenessView.as_view(), name="liveness"),
    path("readyz", ReadinessView.as_view(), name="readiness"),
    path("version", VersionView.as_view(), name="version"),
]
