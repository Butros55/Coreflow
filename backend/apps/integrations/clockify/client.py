"""Clockify API client.

Implements the contract in docs/integrations/clockify.md:
  * Auth is a single ``X-Api-Key`` header (profile → "Manage API keys").
  * Everything except ``/user`` and ``/workspaces`` is workspace-scoped:
    ``/workspaces/{workspaceId}/…``. The workspace id comes from
    ``CLOCKIFY_WORKSPACE_ID`` or, when unset, from the authenticated user's
    ``activeWorkspace``/``defaultWorkspace`` (resolved once per client).
  * List endpoints return **bare JSON arrays** — no envelope, no total count.
    Pagination is ``page``/``page-size``; the last page is the first short one.
  * Time entries are per user: ``/workspaces/{id}/user/{userId}/time-entries``.
    Creating entries for *another* user needs admin rights ("Add time for
    others"); creating for the key's own user is ``POST …/time-entries``.
  * Errors are ``{"message": …, "code": …}``; the numeric code is provider
    internal, so mapping happens on the HTTP status.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
from django.conf import settings

from apps.core.logging import get_logger
from apps.integrations.base import (
    BaseHTTPClient,
    HTTPClientConfig,
    ProviderHTTPError,
    TokenBucketLimiter,
)

logger = get_logger("integrations.clockify")

# Clockify allows ~50 req/s per addon/API key; a modest shared bucket keeps us
# far below that even with several Celery tasks running concurrently.
_CLOCKIFY_LIMITER = TokenBucketLimiter(rate_per_second=5.0, burst=5)

PAGE_SIZE = 200


class ClockifyError(ProviderHTTPError):
    """Clockify error. Matched on the HTTP status, never the message text."""


class ClockifyClient(BaseHTTPClient):
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key if api_key is not None else settings.CLOCKIFY_API_KEY
        config = HTTPClientConfig(
            base_url=base_url or settings.CLOCKIFY_API_BASE_URL,
            timeout=settings.CLOCKIFY_TIMEOUT_SECONDS,
            max_retries=settings.CLOCKIFY_MAX_RETRIES,
            rate_per_second=5.0,
            default_headers={"Accept": "application/json"},
        )
        super().__init__(config, limiter=_CLOCKIFY_LIMITER)
        self._workspace_id: str = settings.CLOCKIFY_WORKSPACE_ID or ""

    def auth_headers(self) -> dict[str, str]:
        return {"X-Api-Key": self._api_key}

    def parse_error(self, response: httpx.Response) -> ClockifyError:
        status = response.status_code
        retryable = status in self.RETRYABLE_STATUSES
        try:
            body = response.json()
        except ValueError:
            body = {}
        message = f"Clockify-Fehler (HTTP {status})"
        if isinstance(body, dict) and body.get("message"):
            message = str(body["message"])
        code = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            429: "rate_limited",
        }.get(status, "provider_error")
        return ClockifyError(
            message, status_code=status, code=code, payload=body, retryable=retryable
        )

    # -- account -----------------------------------------------------------

    def get_current_user(self) -> dict[str, Any]:
        """Connection test: the authenticated user, incl. the workspace ids."""
        return cast("dict[str, Any]", self.get("/user").json())

    def list_workspaces(self) -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", self.get("/workspaces").json())

    @property
    def workspace_id(self) -> str:
        """The remote workspace all scoped calls run against.

        ``CLOCKIFY_WORKSPACE_ID`` wins when set; otherwise the authenticated
        user's active (falling back to default) workspace. Resolved lazily and
        cached — most calls in a sync session share one client instance.
        """
        if not self._workspace_id:
            me = self.get_current_user()
            self._workspace_id = str(me.get("activeWorkspace") or me.get("defaultWorkspace") or "")
            if not self._workspace_id:
                workspaces = self.list_workspaces()
                if workspaces:
                    self._workspace_id = str(workspaces[0].get("id") or "")
            if not self._workspace_id:
                raise ClockifyError(
                    "Kein Clockify-Workspace gefunden. CLOCKIFY_WORKSPACE_ID setzen.",
                    code="no_workspace",
                )
        return self._workspace_id

    # -- paged lists (bare arrays) ------------------------------------------

    def _list(
        self, path: str, page: int, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        merged = {"page": page, "page-size": PAGE_SIZE, **(params or {})}
        return cast("list[dict[str, Any]]", self.get(path, params=merged).json())

    def iter_pages(self, fetch: Any) -> list[dict[str, Any]]:
        """Collect every page of a bare-array list endpoint."""
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            chunk = fetch(page) or []
            items.extend(chunk)
            if len(chunk) < PAGE_SIZE:
                return items
            page += 1

    # -- clients (Clockify "clients" = Coreflow CRM clients) ----------------

    def list_clients(self, page: int = 1) -> list[dict[str, Any]]:
        return self._list(f"/workspaces/{self.workspace_id}/clients", page, {"archived": "false"})

    def get_client(self, client_id: str) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.get(f"/workspaces/{self.workspace_id}/clients/{client_id}").json(),
        )

    def create_client(self, payload: dict[str, Any]) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.post(f"/workspaces/{self.workspace_id}/clients", json=payload).json(),
        )

    # -- projects -----------------------------------------------------------

    def list_projects(self, page: int = 1) -> list[dict[str, Any]]:
        return self._list(f"/workspaces/{self.workspace_id}/projects", page, {"archived": "false"})

    def get_project(self, project_id: str) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.get(f"/workspaces/{self.workspace_id}/projects/{project_id}").json(),
        )

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.post(f"/workspaces/{self.workspace_id}/projects", json=payload).json(),
        )

    # -- tags (↔ Coreflow service types) ------------------------------------

    def list_tags(self, page: int = 1) -> list[dict[str, Any]]:
        return self._list(f"/workspaces/{self.workspace_id}/tags", page)

    def create_tag(self, payload: dict[str, Any]) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.post(f"/workspaces/{self.workspace_id}/tags", json=payload).json(),
        )

    # -- tasks (per project, synced lazily via entries) ----------------------

    def get_task(self, project_id: str, task_id: str) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.get(
                f"/workspaces/{self.workspace_id}/projects/{project_id}/tasks/{task_id}"
            ).json(),
        )

    def list_tasks(self, project_id: str, page: int = 1) -> list[dict[str, Any]]:
        return self._list(f"/workspaces/{self.workspace_id}/projects/{project_id}/tasks", page)

    def create_task(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.post(
                f"/workspaces/{self.workspace_id}/projects/{project_id}/tasks", json=payload
            ).json(),
        )

    # -- users ---------------------------------------------------------------

    def list_users(self, page: int = 1) -> list[dict[str, Any]]:
        return self._list(f"/workspaces/{self.workspace_id}/users", page)

    # -- time entries ---------------------------------------------------------

    def list_time_entries(
        self, user_id: str, *, start: str, end: str, page: int = 1
    ) -> list[dict[str, Any]]:
        """A user's entries in a window. The listing is per user by design."""
        return self._list(
            f"/workspaces/{self.workspace_id}/user/{user_id}/time-entries",
            page,
            {"start": start, "end": end},
        )

    def get_time_entry(self, entry_id: str) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self.get(f"/workspaces/{self.workspace_id}/time-entries/{entry_id}").json(),
        )

    def create_time_entry(
        self, payload: dict[str, Any], *, user_id: str | None = None
    ) -> dict[str, Any]:
        """POST an entry — for the key's own user, or for ``user_id`` (admin).

        The two paths are distinct in Clockify: the plain endpoint always books
        onto the authenticated user, the per-user endpoint needs the paid
        "Add time for others" capability.
        """
        path = (
            f"/workspaces/{self.workspace_id}/user/{user_id}/time-entries"
            if user_id
            else f"/workspaces/{self.workspace_id}/time-entries"
        )
        # Not idempotent: a timeout after the write would duplicate the entry.
        return cast("dict[str, Any]", self.post(path, json=payload, idempotent=False).json())

    def update_time_entry(self, entry_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """PUT replaces the entry — the payload must carry ALL writable fields
        (start, end, billable, description, projectId, taskId, tagIds); an
        omitted field is cleared remotely, not kept."""
        return cast(
            "dict[str, Any]",
            self.put(
                f"/workspaces/{self.workspace_id}/time-entries/{entry_id}", json=payload
            ).json(),
        )

    def delete_time_entry(self, entry_id: str) -> None:
        self.delete(f"/workspaces/{self.workspace_id}/time-entries/{entry_id}")


def is_clockify_enabled() -> bool:
    return bool(settings.CLOCKIFY_ENABLED and settings.CLOCKIFY_API_KEY)
