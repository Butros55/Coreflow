"""API v1 routes.

Each phase mounts its own router here. Keeping one registry means the OpenAPI
schema and the frontend client stay in step with a single source of truth.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import (
    CsrfView,
    CurrentUserView,
    LoginView,
    LogoutView,
    MembershipViewSet,
    PasswordChangeView,
    SessionView,
    WorkspaceViewSet,
)

router = DefaultRouter()
router.register("workspaces", WorkspaceViewSet, basename="workspace")
router.register("memberships", MembershipViewSet, basename="membership")

auth_patterns = [
    path("csrf", CsrfView.as_view(), name="csrf"),
    path("login", LoginView.as_view(), name="login"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("session", SessionView.as_view(), name="session"),
    path("password", PasswordChangeView.as_view(), name="password-change"),
    path("me", CurrentUserView.as_view(), name="current-user"),
]

urlpatterns = [
    path("auth/", include((auth_patterns, "auth"))),
    path("", include(router.urls)),
]
