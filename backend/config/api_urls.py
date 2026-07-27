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
from apps.core.audit_views import AuditLogViewSet
from apps.core.portability_views import ExportWorkspaceView, ImportWorkspaceView
from apps.crm.views import (
    ClientActivityViewSet,
    ClientContactViewSet,
    ClientNoteViewSet,
    ClientViewSet,
)
from apps.files.views import StoredFileViewSet
from apps.finance.views import (
    BusinessReportView,
    FinanceDashboardView,
    ReserveSnapshotViewSet,
    ReserveTransferViewSet,
    ReserveView,
    TaxProfileViewSet,
)
from apps.integrations.views import (
    IntegrationStatusView,
    SyncConflictViewSet,
    TestConnectionView,
    TriggerSyncView,
)
from apps.invoicing.views import InvoiceViewSet, OpenTimeEntriesView
from apps.projects.views import (
    BoardViewSet,
    ProjectPhaseViewSet,
    ProjectViewSet,
    SprintViewSet,
    TaskChecklistItemViewSet,
    TaskCommentViewSet,
    TaskViewSet,
)
from apps.scheduling.views import AppointmentViewSet
from apps.timetracking.views import ServiceTypeViewSet, TimeEntryViewSet

router = DefaultRouter()
router.register("workspaces", WorkspaceViewSet, basename="workspace")
router.register("memberships", MembershipViewSet, basename="membership")
# CRM
router.register("clients", ClientViewSet, basename="client")
router.register("client-contacts", ClientContactViewSet, basename="client-contact")
router.register("client-notes", ClientNoteViewSet, basename="client-note")
router.register("client-activities", ClientActivityViewSet, basename="client-activity")
# Projects
router.register("projects", ProjectViewSet, basename="project")
router.register("project-phases", ProjectPhaseViewSet, basename="project-phase")
router.register("boards", BoardViewSet, basename="board")
router.register("sprints", SprintViewSet, basename="sprint")
router.register("tasks", TaskViewSet, basename="task")
router.register("task-comments", TaskCommentViewSet, basename="task-comment")
router.register("task-checklist", TaskChecklistItemViewSet, basename="task-checklist")
# Time tracking
router.register("service-types", ServiceTypeViewSet, basename="service-type")
router.register("time-entries", TimeEntryViewSet, basename="time-entry")
# Invoicing
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("open-entries", OpenTimeEntriesView, basename="open-entry")
# Finance
router.register("tax-profiles", TaxProfileViewSet, basename="tax-profile")
router.register("reserve-snapshots", ReserveSnapshotViewSet, basename="reserve-snapshot")
router.register("reserve-transfers", ReserveTransferViewSet, basename="reserve-transfer")
# Scheduling & files
router.register("appointments", AppointmentViewSet, basename="appointment")
router.register("files", StoredFileViewSet, basename="file")
# Integrations
router.register("sync-conflicts", SyncConflictViewSet, basename="sync-conflict")
router.register("audit-log", AuditLogViewSet, basename="audit-log")

auth_patterns = [
    path("csrf", CsrfView.as_view(), name="csrf"),
    path("login", LoginView.as_view(), name="login"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("session", SessionView.as_view(), name="session"),
    path("password", PasswordChangeView.as_view(), name="password-change"),
    path("me", CurrentUserView.as_view(), name="current-user"),
]

finance_patterns = [
    path("dashboard", FinanceDashboardView.as_view(), name="dashboard"),
    path("reserve", ReserveView.as_view(), name="reserve"),
    path("report", BusinessReportView.as_view(), name="report"),
]

integration_patterns = [
    path("status", IntegrationStatusView.as_view(), name="status"),
    path("<str:provider>/test", TestConnectionView.as_view(), name="test"),
    path("<str:provider>/sync", TriggerSyncView.as_view(), name="sync"),
]

workspace_data_patterns = [
    path("export", ExportWorkspaceView.as_view(), name="export"),
    path("import", ImportWorkspaceView.as_view(), name="import"),
]

urlpatterns = [
    path("auth/", include((auth_patterns, "auth"))),
    path("finance/", include((finance_patterns, "finance"))),
    path("integrations/", include((integration_patterns, "integrations"))),
    path("workspace-data/", include((workspace_data_patterns, "workspace-data"))),
    path("", include(router.urls)),
]
