"""Clockodo synchronisation engine.

Direction rules (docs/integrations/clockodo.md §6):

* **Customers / projects / services** are mirrored both ways *structurally*:
  every remote object gets a local counterpart (matched by name or created),
  every local object gets a remote counterpart (created when missing). After
  linking, CRM fields are NOT continuously synced — a Clockodo customer never
  overwrites a local ``Client``, and mapping lives in ``ExternalObjectLink``.
* **Users** are matched by e-mail only. Sync never creates users anywhere.
* **Entries** are pulled inbound; locally edited Clockodo-originated entries are
  pushed back when the remote side is unchanged; divergence on both sides —
  or any remote change to a locally locked (billed) entry — becomes a
  ``SyncConflict`` for a human. Never auto-merged, never silently dropped.

Idempotency: every write first compares the ``sync_hash`` of the normalised
remote payload (only mirrored fields). Replayed webhooks and overlapping
windows are no-ops by construction.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User, WorkspaceMembership
from apps.core.logging import get_logger
from apps.crm.models import Client, ClientStatus
from apps.integrations.clockodo.client import ClockodoClient
from apps.integrations.clockodo.mapping import (
    billing_status_for,
    customer_payload_from_client,
    entry_is_running,
    entry_is_time_entry,
    entry_update_payload,
    iso_z,
    normalize_customer,
    normalize_entry,
    normalize_project,
    normalize_service,
    parse_iso_z,
    project_payload_from_project,
    remote_hourly_rate,
    service_payload_from_service_type,
)
from apps.integrations.models import (
    ConflictResolutionStatus,
    ExternalObjectLink,
    Provider,
    SyncConflict,
    SyncDirection,
    SyncJob,
    SyncStatus,
    compute_sync_hash,
)
from apps.projects.models import Project
from apps.timetracking.models import BillingStatus, EntrySource, ServiceType, TimeEntry
from apps.timetracking.services import compute_amount, resolve_hourly_rate

if TYPE_CHECKING:
    from apps.accounts.models import Workspace

logger = get_logger("integrations.clockodo.sync")

# Entries in these local states are settled paperwork: a remote change cannot be
# applied silently — it surfaces as a conflict instead.
LOCKED_STATUSES = frozenset(
    {BillingStatus.DRAFT_CREATED, BillingStatus.BILLED, BillingStatus.CANCELLED}
)

# Remote billable → the set of local statuses it is CONSISTENT with. Used to
# recognise convergence (e.g. our own billable=2 push echoing back) instead of
# flagging it as a conflict.
_COMPATIBLE_STATUSES: dict[int, frozenset[str]] = {
    0: frozenset({BillingStatus.NOT_BILLABLE}),
    1: frozenset({BillingStatus.OPEN, BillingStatus.MARKED, BillingStatus.DRAFT_CREATED}),
    2: frozenset({BillingStatus.BILLED}),
}

FULL_SYNC_LOOKBACK_DAYS = 365
FULL_SYNC_WINDOW_DAYS = 31
# Incremental windows cover recent work. The v2 entries listing can only filter
# by the ENTRY's own time, not by time_last_change — edits to older entries
# reach us via webhooks, with the periodic full sync as the backstop.
INCREMENTAL_LOOKBACK_DAYS = 14


class ClockodoSync:
    """One workspace's sync session. Stateless between calls except the client."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        trigger: str = "scheduled",
        triggered_by: User | None = None,
    ) -> None:
        self.workspace = workspace
        self.trigger = trigger
        self.triggered_by = triggered_by

    # -- plumbing ----------------------------------------------------------

    def _job(self, resource_type: str, direction: str, *, is_full: bool) -> SyncJob:
        return SyncJob.objects.create(
            workspace=self.workspace,
            provider=Provider.CLOCKODO,
            resource_type=resource_type,
            direction=direction,
            trigger=self.trigger,
            is_full_sync=is_full,
            triggered_by=self.triggered_by,
        )

    def _links(self, resource_type: str) -> dict[str, ExternalObjectLink]:
        return {
            link.external_id: link
            for link in ExternalObjectLink.objects.filter(
                workspace=self.workspace,
                provider=Provider.CLOCKODO,
                resource_type=resource_type,
            )
        }

    def _create_link(
        self,
        resource_type: str,
        external_id: str,
        local_type: str,
        local_id: Any,
        normalized: dict[str, Any],
    ) -> ExternalObjectLink:
        link = ExternalObjectLink.objects.create(
            workspace=self.workspace,
            provider=Provider.CLOCKODO,
            resource_type=resource_type,
            external_id=external_id,
            local_object_type=local_type,
            local_object_id=local_id,
        )
        link.mark_synced(normalized)
        return link

    def _open_conflict(
        self,
        resource_type: str,
        external_id: str,
        local_type: str,
        local_id: Any,
        *,
        reason: str,
        local_snapshot: dict[str, Any],
        remote_snapshot: dict[str, Any],
        job: SyncJob | None = None,
    ) -> None:
        """Create a conflict once — an already-open one is not re-raised."""
        exists = SyncConflict.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKODO,
            resource_type=resource_type,
            external_id=external_id,
            resolution_status=ConflictResolutionStatus.OPEN,
        ).exists()
        if exists:
            return
        SyncConflict.objects.create(
            workspace=self.workspace,
            provider=Provider.CLOCKODO,
            resource_type=resource_type,
            external_id=external_id,
            local_object_type=local_type,
            local_object_id=local_id,
            reason=reason,
            local_snapshot=local_snapshot,
            remote_snapshot=remote_snapshot,
            sync_job=job,
        )

    @staticmethod
    def _iter_pages(fetch: Any, envelope_key: str) -> list[dict[str, Any]]:
        """Collect all pages of a list endpoint (snake_case paging, §4.2)."""
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            data = fetch(page)
            chunk = data.get(envelope_key) or []
            items.extend(chunk)
            paging = data.get("paging") or {}
            count_pages = int(paging.get("count_pages") or 1)
            if page >= count_pages:
                return items
            page += 1

    # -- customers ---------------------------------------------------------

    def sync_customers(self, client_conn: ClockodoClient) -> SyncJob:
        job = self._job("customer", SyncDirection.BIDIRECTIONAL, is_full=True)
        job.mark_running()
        links = self._links("customer")

        remotes = self._iter_pages(lambda p: client_conn.list_customers(page=p), "data")
        for remote in remotes:
            job.records_processed += 1
            external_id = str(remote.get("id"))
            normalized = normalize_customer(remote)
            link = links.get(external_id)
            if link is not None:
                if link.payload_changed(normalized):
                    # Mapping only — CRM fields of a linked client are never
                    # overwritten by Clockodo (clockodo.md §6).
                    link.mark_synced(normalized)
                    job.records_updated += 1
                else:
                    job.records_skipped += 1
                continue
            outcome = self._link_or_create_client(remote, job=job)
            if outcome == "created":
                job.records_created += 1
            elif outcome == "linked":
                job.records_updated += 1
            else:
                job.records_failed += 1

        # Outbound: every active, unlinked local client gets a remote counterpart.
        linked_local_ids = {
            link.local_object_id
            for link in ExternalObjectLink.objects.filter(
                workspace=self.workspace,
                provider=Provider.CLOCKODO,
                resource_type="customer",
            )
        }
        for local_client in Client.objects.filter(workspace=self.workspace, archived=False).exclude(
            pk__in=linked_local_ids
        ):
            job.records_processed += 1
            created = client_conn.create_customer(customer_payload_from_client(local_client))
            remote_obj = created.get("data") or {}
            if not remote_obj.get("id"):
                job.records_failed += 1
                continue
            self._create_link(
                "customer",
                str(remote_obj["id"]),
                "crm.Client",
                local_client.pk,
                normalize_customer(remote_obj),
            )
            job.records_created += 1

        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    def _link_or_create_client(self, remote: dict[str, Any], job: SyncJob | None = None) -> str:
        """Link a remote customer to a local client by exact name, else mirror it."""
        external_id = str(remote.get("id"))
        name = str(remote.get("name") or "").strip()
        if not name:
            return "failed"
        normalized = normalize_customer(remote)

        linked_ids = ExternalObjectLink.objects.filter(
            workspace=self.workspace, provider=Provider.CLOCKODO, resource_type="customer"
        ).values_list("local_object_id", flat=True)
        matches = list(
            Client.objects.filter(workspace=self.workspace, name__iexact=name).exclude(
                pk__in=linked_ids
            )[:2]
        )
        if len(matches) > 1:
            self._open_conflict(
                "customer",
                external_id,
                "crm.Client",
                None,
                reason="ambiguous_match",
                local_snapshot={"candidates": [str(m.pk) for m in matches], "name": name},
                remote_snapshot=normalized,
                job=job,
            )
            return "failed"
        if matches:
            self._create_link("customer", external_id, "crm.Client", matches[0].pk, normalized)
            return "linked"

        local_client = Client.objects.create(
            workspace=self.workspace,
            name=name,
            status=ClientStatus.ACTIVE,
            archived=not bool(remote.get("active", True)),
        )
        self._create_link("customer", external_id, "crm.Client", local_client.pk, normalized)
        return "created"

    # -- projects ----------------------------------------------------------

    def sync_projects(self, client_conn: ClockodoClient) -> SyncJob:
        job = self._job("project", SyncDirection.BIDIRECTIONAL, is_full=True)
        job.mark_running()
        links = self._links("project")
        customer_links = self._links("customer")

        remotes = self._iter_pages(lambda p: client_conn.list_projects(page=p), "data")
        for remote in remotes:
            job.records_processed += 1
            external_id = str(remote.get("id"))
            normalized = normalize_project(remote)
            link = links.get(external_id)
            if link is not None:
                if link.payload_changed(normalized):
                    link.mark_synced(normalized)
                    job.records_updated += 1
                else:
                    job.records_skipped += 1
                continue
            outcome = self._link_or_create_project(remote, customer_links, job=job)
            if outcome == "created":
                job.records_created += 1
            elif outcome == "linked":
                job.records_updated += 1
            else:
                job.records_failed += 1

        # Outbound: unlinked active local projects whose client has a remote id.
        linked_local_ids = {
            link.local_object_id
            for link in ExternalObjectLink.objects.filter(
                workspace=self.workspace, provider=Provider.CLOCKODO, resource_type="project"
            )
        }
        client_remote_by_local = {
            link.local_object_id: int(link.external_id) for link in self._links("customer").values()
        }
        for project in (
            Project.objects.filter(workspace=self.workspace, archived=False)
            .exclude(pk__in=linked_local_ids)
            .select_related("client")
        ):
            remote_customer_id = client_remote_by_local.get(project.client_id)
            if remote_customer_id is None:
                continue  # Client not pushed (archived) — nothing to hang it on.
            job.records_processed += 1
            created = client_conn.create_project(
                project_payload_from_project(project, remote_customer_id)
            )
            remote_obj = created.get("data") or {}
            if not remote_obj.get("id"):
                job.records_failed += 1
                continue
            self._create_link(
                "project",
                str(remote_obj["id"]),
                "projects.Project",
                project.pk,
                normalize_project(remote_obj),
            )
            job.records_created += 1

        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    def _link_or_create_project(
        self,
        remote: dict[str, Any],
        customer_links: dict[str, ExternalObjectLink],
        job: SyncJob | None = None,
    ) -> str:
        external_id = str(remote.get("id"))
        name = str(remote.get("name") or "").strip()
        customer_link = customer_links.get(str(remote.get("customers_id")))
        if not name or customer_link is None:
            return "failed"
        normalized = normalize_project(remote)

        linked_ids = ExternalObjectLink.objects.filter(
            workspace=self.workspace, provider=Provider.CLOCKODO, resource_type="project"
        ).values_list("local_object_id", flat=True)
        matches = list(
            Project.objects.filter(
                workspace=self.workspace,
                client_id=customer_link.local_object_id,
                name__iexact=name,
            ).exclude(pk__in=linked_ids)[:2]
        )
        if len(matches) > 1:
            self._open_conflict(
                "project",
                external_id,
                "projects.Project",
                None,
                reason="ambiguous_match",
                local_snapshot={"candidates": [str(m.pk) for m in matches], "name": name},
                remote_snapshot=normalized,
                job=job,
            )
            return "failed"
        if matches:
            self._create_link("project", external_id, "projects.Project", matches[0].pk, normalized)
            return "linked"

        project = Project.objects.create(
            workspace=self.workspace,
            client_id=customer_link.local_object_id,
            name=name,
            archived=not bool(remote.get("active", True)),
        )
        self._create_link("project", external_id, "projects.Project", project.pk, normalized)
        return "created"

    # -- services ----------------------------------------------------------

    def sync_services(self, client_conn: ClockodoClient) -> SyncJob:
        job = self._job("service", SyncDirection.BIDIRECTIONAL, is_full=True)
        job.mark_running()
        links = self._links("service")

        remotes = self._iter_pages(lambda p: client_conn.list_services(page=p), "data")
        for remote in remotes:
            job.records_processed += 1
            external_id = str(remote.get("id"))
            name = str(remote.get("name") or "").strip()
            normalized = normalize_service(remote)
            link = links.get(external_id)
            if link is not None:
                if link.payload_changed(normalized):
                    link.mark_synced(normalized)
                    job.records_updated += 1
                else:
                    job.records_skipped += 1
                continue
            if not name:
                job.records_failed += 1
                continue
            linked_ids = ExternalObjectLink.objects.filter(
                workspace=self.workspace, provider=Provider.CLOCKODO, resource_type="service"
            ).values_list("local_object_id", flat=True)
            match = (
                ServiceType.objects.filter(workspace=self.workspace, name__iexact=name)
                .exclude(pk__in=linked_ids)
                .first()
            )
            if match is None:
                match = ServiceType.objects.create(
                    workspace=self.workspace, name=name, active=bool(remote.get("active", True))
                )
                job.records_created += 1
            else:
                job.records_updated += 1
            self._create_link(
                "service", external_id, "timetracking.ServiceType", match.pk, normalized
            )

        linked_local_ids = {
            link.local_object_id
            for link in ExternalObjectLink.objects.filter(
                workspace=self.workspace, provider=Provider.CLOCKODO, resource_type="service"
            )
        }
        for service_type in ServiceType.objects.filter(
            workspace=self.workspace, active=True
        ).exclude(pk__in=linked_local_ids):
            job.records_processed += 1
            created = client_conn.create_service(service_payload_from_service_type(service_type))
            remote_obj = created.get("data") or {}
            if not remote_obj.get("id"):
                job.records_failed += 1
                continue
            self._create_link(
                "service",
                str(remote_obj["id"]),
                "timetracking.ServiceType",
                service_type.pk,
                normalize_service(remote_obj),
            )
            job.records_created += 1

        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    # -- users -------------------------------------------------------------

    def sync_users(self, client_conn: ClockodoClient) -> SyncJob:
        """Match Clockodo users to workspace members by e-mail. Never creates."""
        job = self._job("user", SyncDirection.INBOUND, is_full=True)
        job.mark_running()
        links = self._links("user")

        members = {
            membership.user.email.lower(): membership.user
            for membership in WorkspaceMembership.objects.filter(
                workspace=self.workspace
            ).select_related("user")
        }
        remotes = self._iter_pages(lambda p: client_conn.list_users(page=p), "data")
        for remote in remotes:
            job.records_processed += 1
            external_id = str(remote.get("id"))
            if external_id in links:
                job.records_skipped += 1
                continue
            email = str(remote.get("email") or "").lower()
            local_user = members.get(email)
            if local_user is None:
                job.records_skipped += 1
                continue
            self._create_link(
                "user",
                external_id,
                "accounts.User",
                local_user.pk,
                {"id": remote.get("id"), "email": email},
            )
            job.records_created += 1

        job.save()
        job.mark_finished(SyncStatus.SUCCESS)
        return job

    # -- entries -----------------------------------------------------------

    def sync_entries(
        self,
        client_conn: ClockodoClient,
        *,
        since: dt.datetime,
        until: dt.datetime,
        is_full: bool = False,
    ) -> SyncJob:
        job = self._job("entry", SyncDirection.BIDIRECTIONAL, is_full=is_full)
        job.mark_running()

        seen_external: set[str] = set()
        window_start = since
        while window_start < until:
            window_end = min(window_start + dt.timedelta(days=FULL_SYNC_WINDOW_DAYS), until)
            remotes = self._iter_pages(
                lambda p: client_conn.list_entries(
                    time_since=iso_z(window_start),  # noqa: B023 - consumed eagerly
                    time_until=iso_z(window_end),  # noqa: B023
                    page=p,
                ),
                "entries",
            )
            for remote in remotes:
                job.records_processed += 1
                external_id = str(remote.get("id"))
                seen_external.add(external_id)
                outcome = self.apply_remote_entry(remote, client_conn=client_conn, job=job)
                if outcome == "created":
                    job.records_created += 1
                elif outcome in {"updated", "pushed"}:
                    job.records_updated += 1
                elif outcome == "failed":
                    job.records_failed += 1
                else:  # unchanged / skipped_* / conflict
                    job.records_skipped += 1
            job.cursor = {"window_end": iso_z(window_end)}
            job.save()
            window_start = window_end

        if is_full:
            self._reconcile_window_deletions(since, until, seen_external, job)

        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    def apply_remote_entry(
        self,
        remote: dict[str, Any],
        *,
        client_conn: ClockodoClient | None,
        job: SyncJob | None = None,
    ) -> str:
        """Reconcile one remote entry. Returns the outcome for job accounting."""
        if not entry_is_time_entry(remote):
            return "skipped_lumpsum"
        if entry_is_running(remote):
            # The local single-running-timer constraint belongs to local timers;
            # a Clockodo clock is imported once it stops (entry.stopped webhook
            # or the next sync window).
            return "skipped_running"

        external_id = str(remote.get("id"))
        normalized = normalize_entry(remote)
        link = (
            ExternalObjectLink.objects.filter(
                workspace=self.workspace,
                provider=Provider.CLOCKODO,
                resource_type="entry",
                external_id=external_id,
            )
            .select_related(None)
            .first()
        )
        if link is None:
            return self._create_entry_from_remote(remote, normalized, client_conn=client_conn)

        entry = TimeEntry.objects.filter(workspace=self.workspace, pk=link.local_object_id).first()
        if entry is None:
            # The local mirror vanished (deleted locally). Re-creating it would
            # resurrect data a human deliberately removed — surface instead.
            self._open_conflict(
                "entry",
                external_id,
                "timetracking.TimeEntry",
                link.local_object_id,
                reason="concurrent_modification",
                local_snapshot={"deleted_locally": True},
                remote_snapshot=normalized,
                job=job,
            )
            return "conflict"

        remote_changed = link.payload_changed(normalized)
        local_changed = bool(
            link.last_synced_at is not None and entry.updated_at > link.last_synced_at
        )

        if not remote_changed and not local_changed:
            return "unchanged"

        if remote_changed and self._entry_matches_remote(entry, remote):
            # Convergent: e.g. our own billable=2 push echoing back. Just adopt
            # the new hash so the next pass is a clean no-op.
            link.mark_synced(normalized)
            return "unchanged"

        if remote_changed and entry.billing_status in LOCKED_STATUSES:
            self._open_conflict(
                "entry",
                external_id,
                "timetracking.TimeEntry",
                entry.pk,
                reason="concurrent_modification",
                local_snapshot=self._entry_snapshot(entry),
                remote_snapshot=normalized,
                job=job,
            )
            return "conflict"

        if remote_changed and local_changed:
            self._open_conflict(
                "entry",
                external_id,
                "timetracking.TimeEntry",
                entry.pk,
                reason="concurrent_modification",
                local_snapshot=self._entry_snapshot(entry),
                remote_snapshot=normalized,
                job=job,
            )
            return "conflict"

        if remote_changed:
            self._apply_remote_fields(entry, remote)
            link.mark_synced(normalized)
            return "updated"

        # Local changed, remote unchanged → push back (clockodo.md §6).
        if client_conn is None or entry.billing_status in LOCKED_STATUSES:
            return "unchanged"
        response = client_conn.update_entry(int(external_id), entry_update_payload(entry))
        remote_after = response.get("entry") or {}
        link.mark_synced(normalize_entry(remote_after) if remote_after else normalized)
        return "pushed"

    def _create_entry_from_remote(
        self,
        remote: dict[str, Any],
        normalized: dict[str, Any],
        *,
        client_conn: ClockodoClient | None,
    ) -> str:
        user_link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKODO,
            resource_type="user",
            external_id=str(remote.get("users_id")),
        ).first()
        if user_link is None:
            return "skipped_no_user"
        user = User.objects.filter(pk=user_link.local_object_id).first()
        if user is None:
            return "skipped_no_user"

        customer_link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKODO,
            resource_type="customer",
            external_id=str(remote.get("customers_id")),
        ).first()
        if customer_link is None and client_conn is not None:
            fetched = client_conn.get_customer(int(remote["customers_id"]))
            remote_customer = fetched.get("data") or {}
            if remote_customer.get("id"):
                self._link_or_create_client(remote_customer)
                customer_link = ExternalObjectLink.objects.filter(
                    workspace=self.workspace,
                    provider=Provider.CLOCKODO,
                    resource_type="customer",
                    external_id=str(remote_customer["id"]),
                ).first()
        if customer_link is None:
            return "failed"
        local_client = Client.objects.filter(pk=customer_link.local_object_id).first()
        if local_client is None:
            return "failed"

        project = None
        if remote.get("projects_id"):
            project_link = ExternalObjectLink.objects.filter(
                workspace=self.workspace,
                provider=Provider.CLOCKODO,
                resource_type="project",
                external_id=str(remote["projects_id"]),
            ).first()
            if project_link is not None:
                project = Project.objects.filter(pk=project_link.local_object_id).first()

        service_type = None
        if remote.get("services_id"):
            service_link = ExternalObjectLink.objects.filter(
                workspace=self.workspace,
                provider=Provider.CLOCKODO,
                resource_type="service",
                external_id=str(remote["services_id"]),
            ).first()
            if service_link is not None:
                service_type = ServiceType.objects.filter(pk=service_link.local_object_id).first()

        started_at = parse_iso_z(str(remote["time_since"]))
        ended_at = parse_iso_z(str(remote["time_until"]))
        duration = int(remote.get("duration") or (ended_at - started_at).total_seconds())
        billable_raw = int(remote.get("billable", 1))
        billable = billable_raw != 0
        rate = remote_hourly_rate(remote) or resolve_hourly_rate(
            workspace=self.workspace,
            client=local_client,
            project=project,
            service_type=service_type,
            explicit=None,
        )

        with transaction.atomic():
            entry = TimeEntry.objects.create(
                workspace=self.workspace,
                user=user,
                client=local_client,
                project=project,
                service_type=service_type,
                description=str(remote.get("text") or ""),
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=duration,
                source=EntrySource.CLOCKODO,
                billable=billable,
                hourly_rate=rate,
                computed_amount=compute_amount(
                    duration_seconds=duration, hourly_rate=rate, billable=billable
                ),
                billing_status=billing_status_for(billable_raw),
            )
            self._create_link(
                "entry", str(remote["id"]), "timetracking.TimeEntry", entry.pk, normalized
            )
        return "created"

    def _apply_remote_fields(self, entry: TimeEntry, remote: dict[str, Any]) -> None:
        started_at = parse_iso_z(str(remote["time_since"]))
        ended_at = parse_iso_z(str(remote["time_until"]))
        duration = int(remote.get("duration") or (ended_at - started_at).total_seconds())
        billable_raw = int(remote.get("billable", 1))

        entry.started_at = started_at
        entry.ended_at = ended_at
        entry.duration_seconds = duration
        entry.description = str(remote.get("text") or "")
        entry.billable = billable_raw != 0
        # Only move along the axis Clockodo owns; local workflow states
        # (marked_for_invoice) survive a remote edit that kept billable=1.
        remote_status = billing_status_for(billable_raw)
        if entry.billing_status not in _COMPATIBLE_STATUSES.get(billable_raw, frozenset()):
            entry.billing_status = remote_status
        entry.computed_amount = compute_amount(
            duration_seconds=duration, hourly_rate=entry.hourly_rate, billable=entry.billable
        )
        entry.save()

    def _entry_matches_remote(self, entry: TimeEntry, remote: dict[str, Any]) -> bool:
        """True when local and remote agree on every mirrored field."""
        if entry.ended_at is None:
            return False
        started_at = parse_iso_z(str(remote["time_since"]))
        ended_at = parse_iso_z(str(remote["time_until"])) if remote.get("time_until") else None
        billable_raw = int(remote.get("billable", 1))
        compatible = _COMPATIBLE_STATUSES.get(billable_raw)
        return (
            entry.started_at == started_at
            and entry.ended_at == ended_at
            and int(entry.duration_seconds) == int(remote.get("duration") or 0)
            and entry.description == str(remote.get("text") or "")
            and (compatible is None or entry.billing_status in compatible)
        )

    @staticmethod
    def _entry_snapshot(entry: TimeEntry) -> dict[str, Any]:
        return {
            "started_at": entry.started_at.isoformat(),
            "ended_at": entry.ended_at.isoformat() if entry.ended_at else None,
            "duration_seconds": entry.duration_seconds,
            "description": entry.description,
            "billable": entry.billable,
            "billing_status": entry.billing_status,
        }

    def _reconcile_window_deletions(
        self,
        since: dt.datetime,
        until: dt.datetime,
        seen_external: set[str],
        job: SyncJob,
    ) -> None:
        """Full sync only: linked entries inside the window that the API no
        longer returns were deleted in Clockodo."""
        candidate_links = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKODO,
            resource_type="entry",
            deleted_remotely=False,
        ).exclude(external_id__in=seen_external)
        for link in candidate_links:
            entry = TimeEntry.objects.filter(
                workspace=self.workspace,
                pk=link.local_object_id,
                started_at__gte=since,
                started_at__lt=until,
            ).first()
            if entry is None:
                continue
            self.handle_entry_deleted(link, entry, job=job)

    def handle_entry_deleted(
        self, link: ExternalObjectLink, entry: TimeEntry | None, job: SyncJob | None = None
    ) -> str:
        """Remote entry gone: mirror the deletion, unless local is settled."""
        link.deleted_remotely = True
        link.save(update_fields=["deleted_remotely", "updated_at"])
        if entry is None:
            return "unchanged"
        if entry.billing_status in LOCKED_STATUSES:
            self._open_conflict(
                "entry",
                link.external_id,
                "timetracking.TimeEntry",
                entry.pk,
                reason="remote_deleted",
                local_snapshot=self._entry_snapshot(entry),
                remote_snapshot={},
                job=job,
            )
            return "conflict"
        entry.delete()
        return "deleted"

    # -- single-entity appliers (webhooks) ---------------------------------

    def apply_remote_customer(self, remote: dict[str, Any]) -> str:
        external_id = str(remote.get("id"))
        normalized = normalize_customer(remote)
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKODO,
            resource_type="customer",
            external_id=external_id,
        ).first()
        if link is not None:
            if link.payload_changed(normalized):
                link.mark_synced(normalized)
                return "updated"
            return "unchanged"
        return self._link_or_create_client(remote)

    def apply_remote_project(self, remote: dict[str, Any]) -> str:
        external_id = str(remote.get("id"))
        normalized = normalize_project(remote)
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKODO,
            resource_type="project",
            external_id=external_id,
        ).first()
        if link is not None:
            if link.payload_changed(normalized):
                link.mark_synced(normalized)
                return "updated"
            return "unchanged"
        return self._link_or_create_project(remote, self._links("customer"))

    def mark_link_deleted(self, resource_type: str, external_id: str) -> str:
        """customer.deleted / project.deleted: flag the link; local CRM objects
        are Coreflow's and are never deleted by a provider."""
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKODO,
            resource_type=resource_type,
            external_id=external_id,
        ).first()
        if link is None:
            return "unchanged"
        link.deleted_remotely = True
        link.save(update_fields=["deleted_remotely", "updated_at"])
        return "updated"

    # -- orchestration -----------------------------------------------------

    def full_sync(self, client_conn: ClockodoClient) -> list[SyncJob]:
        """Connect-time / manual full sync: masters first, then entries."""
        now = timezone.now()
        jobs = [
            self.sync_customers(client_conn),
            self.sync_projects(client_conn),
            self.sync_services(client_conn),
            self.sync_users(client_conn),
            self.sync_entries(
                client_conn,
                since=now - dt.timedelta(days=FULL_SYNC_LOOKBACK_DAYS),
                until=now + dt.timedelta(minutes=5),
                is_full=True,
            ),
        ]
        logger.info(
            "clockodo_full_sync_done",
            workspace_id=str(self.workspace.pk),
            jobs={job.resource_type: job.status for job in jobs},
        )
        return jobs

    def incremental_sync(self, client_conn: ClockodoClient) -> SyncJob:
        now = timezone.now()
        return self.sync_entries(
            client_conn,
            since=now - dt.timedelta(days=INCREMENTAL_LOOKBACK_DAYS),
            until=now + dt.timedelta(minutes=5),
            is_full=False,
        )


def entry_links_for(entry_ids: list[Any], workspace: Workspace) -> dict[Any, str]:
    """Map local TimeEntry ids → Clockodo entry ids, for the billed push."""
    return {
        link.local_object_id: link.external_id
        for link in ExternalObjectLink.objects.filter(
            workspace=workspace,
            provider=Provider.CLOCKODO,
            resource_type="entry",
            local_object_id__in=entry_ids,
            deleted_remotely=False,
        )
    }


def push_entries_billed(workspace: Workspace, entry_ids: list[Any]) -> int:
    """PUT billable=2 for every linked entry of a billed invoice (§5.7).

    Per-entry PUT, not entrygroups: exact, no confirm_key round-trip, and the
    10/min entrygroup cap makes bulk the worse option for typical invoices.
    """
    links = entry_links_for(entry_ids, workspace)
    if not links:
        return 0
    pushed = 0
    with ClockodoClient() as client_conn:
        for local_id, external_id in links.items():
            response = client_conn.update_entry(int(external_id), {"billable": 2})
            remote_after = response.get("entry") or {}
            link = ExternalObjectLink.objects.get(
                workspace=workspace,
                provider=Provider.CLOCKODO,
                resource_type="entry",
                local_object_id=local_id,
            )
            if remote_after:
                link.mark_synced(normalize_entry(remote_after))
            pushed += 1
    logger.info("clockodo_billed_pushed", workspace_id=str(workspace.pk), count=pushed)
    return pushed


def compute_remote_entry_hash(remote: dict[str, Any]) -> str:
    """Convenience for tests: hash exactly as the sync does."""
    return compute_sync_hash(normalize_entry(remote))
