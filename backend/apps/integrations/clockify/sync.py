"""Clockify synchronisation engine.

Direction rules (docs/integrations/clockify.md §5):

* **Clients / projects / tags** are mirrored both ways *structurally*: every
  remote object gets a local counterpart (matched by name or created), every
  local object gets a remote counterpart (created when missing). After linking,
  CRM fields are NOT continuously synced — a Clockify client never overwrites a
  local ``Client``; the mapping lives in ``ExternalObjectLink``.
* **Users** are matched by e-mail only. Sync never creates users anywhere.
* **Tasks** are linked lazily through entries (matched by title within the
  linked project). Local tasks are never created from Clockify — a local Task
  needs a board — and Clockify tasks are created on demand when pushing an
  entry that references a local task.
* **Entries** flow both ways: remote entries are pulled in, local entries
  (manual/timer, recent window) are pushed out, local edits to linked entries
  are pushed back while the remote side is unchanged. Divergence on both sides
  — or any remote change to a locally settled (billed) entry — becomes a
  ``SyncConflict`` for a human. Never auto-merged, never silently dropped.

**Lexware deduplication** (the "one entry, two tags" rule): before a remote
entry is mirrored as a new ``TimeEntry``, the sync looks for an existing local
twin — an identical unlinked entry (same client, same start ±60 s, same hours)
or a Lexware-reconstructed entry whose invoice period covers the remote entry
(same client, same hours). A twin is *linked*, not duplicated: the entry keeps
its Lexware provenance and gains the Clockify link, so the UI shows both tags
on one row instead of two rows.

Idempotency: every write first compares the ``sync_hash`` of the normalised
remote payload (only mirrored fields). Replayed webhooks and overlapping
windows are no-ops by construction.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User, WorkspaceMembership
from apps.core.logging import get_logger
from apps.core.money import money, seconds_to_hours
from apps.crm.models import Client, ClientStatus
from apps.integrations.clockify.client import ClockifyClient, ClockifyError
from apps.integrations.clockify.mapping import (
    BILLED_TAG_NAME,
    billing_status_for,
    client_payload_from_client,
    entry_duration_seconds,
    entry_is_running,
    entry_payload,
    iso_z,
    normalize_client,
    normalize_entry,
    normalize_project,
    normalize_tag,
    parse_iso_z,
    project_payload_from_project,
    tag_payload_from_service_type,
    task_payload_from_task,
)
from apps.integrations.models import (
    ConflictResolutionStatus,
    ExternalObjectLink,
    Provider,
    ProviderProfile,
    SyncConflict,
    SyncDirection,
    SyncJob,
    SyncStatus,
    compute_sync_hash,
)
from apps.projects.models import Project, Task
from apps.timetracking.models import BillingStatus, EntrySource, ServiceType, TimeEntry
from apps.timetracking.services import compute_amount, resolve_hourly_rate

if TYPE_CHECKING:
    from apps.accounts.models import Workspace

logger = get_logger("integrations.clockify.sync")

# Entries in these local states are settled paperwork: a remote change cannot be
# applied silently — it surfaces as a conflict instead.
LOCKED_STATUSES = frozenset(
    {BillingStatus.DRAFT_CREATED, BillingStatus.BILLED, BillingStatus.CANCELLED}
)

# Remote billable → the set of local statuses it is CONSISTENT with. Clockify
# has no "billed" state, so a billed local entry stays billable=true remotely
# (plus the BILLED_TAG_NAME tag) — that combination is convergence, not drift.
_COMPATIBLE_STATUSES: dict[bool, frozenset[str]] = {
    False: frozenset({BillingStatus.NOT_BILLABLE}),
    True: frozenset(
        {
            BillingStatus.OPEN,
            BillingStatus.MARKED,
            BillingStatus.DRAFT_CREATED,
            BillingStatus.BILLED,
        }
    ),
}

FULL_SYNC_LOOKBACK_DAYS = 365
FULL_SYNC_WINDOW_DAYS = 31
# Incremental windows cover recent work; edits to older entries reach us via
# webhooks, with the periodic full sync as the backstop.
INCREMENTAL_LOOKBACK_DAYS = 14

# Remote projects can live without a client; local ones cannot. They hang off
# this auto-created placeholder so nothing is dropped.
NO_CLIENT_PLACEHOLDER = "Clockify (ohne Kunde)"

# Local sources that are pushed to Clockify when unlinked. Lexware
# reconstructions are deliberately absent: their timestamps are synthetic
# (stacked from 09:00 of the invoice period) and their hours are already
# represented in Lexware — pushing them would fill Clockify with fake times.
PUSHABLE_SOURCES = (EntrySource.MANUAL, EntrySource.TIMER)


class ClockifySync:
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
        self._billed_tag_id: str | None = None

    # -- plumbing ----------------------------------------------------------

    def _job(self, resource_type: str, direction: str, *, is_full: bool) -> SyncJob:
        return SyncJob.objects.create(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
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
                provider=Provider.CLOCKIFY,
                resource_type=resource_type,
            )
        }

    def _link_for_local(self, resource_type: str, local_id: Any) -> ExternalObjectLink | None:
        return ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type=resource_type,
            local_object_id=local_id,
            deleted_remotely=False,
        ).first()

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
            provider=Provider.CLOCKIFY,
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
            provider=Provider.CLOCKIFY,
            resource_type=resource_type,
            external_id=external_id,
            resolution_status=ConflictResolutionStatus.OPEN,
        ).exists()
        if exists:
            return
        SyncConflict.objects.create(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type=resource_type,
            external_id=external_id,
            local_object_type=local_type,
            local_object_id=local_id,
            reason=reason,
            local_snapshot=local_snapshot,
            remote_snapshot=remote_snapshot,
            sync_job=job,
        )

    def _remote_me_id(self) -> str:
        """The Clockify user id behind the API key (cached on connect)."""
        profile = ProviderProfile.objects.filter(
            workspace=self.workspace, provider=Provider.CLOCKIFY
        ).first()
        if profile is None:
            return ""
        return str((profile.raw_profile.get("user") or {}).get("id") or "")

    # -- clients -----------------------------------------------------------

    def sync_clients(self, client_conn: ClockifyClient) -> SyncJob:
        job = self._job("client", SyncDirection.BIDIRECTIONAL, is_full=True)
        job.mark_running()
        links = self._links("client")

        remotes = client_conn.iter_pages(lambda p: client_conn.list_clients(page=p))
        for remote in remotes:
            job.records_processed += 1
            external_id = str(remote.get("id"))
            normalized = normalize_client(remote)
            link = links.get(external_id)
            if link is not None:
                if link.payload_changed(normalized):
                    # Mapping only — CRM fields of a linked client are never
                    # overwritten by Clockify (clockify.md §5).
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

        self._push_unlinked_clients(client_conn, job)
        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    def _push_unlinked_clients(self, client_conn: ClockifyClient, job: SyncJob) -> None:
        """Outbound: every active, unlinked local client gets a remote twin."""
        linked_local_ids = {
            link.local_object_id
            for link in ExternalObjectLink.objects.filter(
                workspace=self.workspace, provider=Provider.CLOCKIFY, resource_type="client"
            )
        }
        for local_client in (
            Client.objects.filter(workspace=self.workspace, archived=False)
            .exclude(pk__in=linked_local_ids)
            .exclude(name=NO_CLIENT_PLACEHOLDER)
        ):
            job.records_processed += 1
            created = client_conn.create_client(client_payload_from_client(local_client))
            if not created.get("id"):
                job.records_failed += 1
                continue
            self._create_link(
                "client",
                str(created["id"]),
                "crm.Client",
                local_client.pk,
                normalize_client(created),
            )
            job.records_created += 1

    def _link_or_create_client(self, remote: dict[str, Any], job: SyncJob | None = None) -> str:
        """Link a remote client to a local one by exact name, else mirror it."""
        external_id = str(remote.get("id"))
        name = str(remote.get("name") or "").strip()
        if not name:
            return "failed"
        normalized = normalize_client(remote)

        linked_ids = ExternalObjectLink.objects.filter(
            workspace=self.workspace, provider=Provider.CLOCKIFY, resource_type="client"
        ).values_list("local_object_id", flat=True)
        matches = list(
            Client.objects.filter(workspace=self.workspace, name__iexact=name).exclude(
                pk__in=linked_ids
            )[:2]
        )
        if len(matches) > 1:
            self._open_conflict(
                "client",
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
            self._create_link("client", external_id, "crm.Client", matches[0].pk, normalized)
            return "linked"

        local_client = Client.objects.create(
            workspace=self.workspace,
            name=name,
            status=ClientStatus.ACTIVE,
            archived=bool(remote.get("archived", False)),
        )
        self._create_link("client", external_id, "crm.Client", local_client.pk, normalized)
        return "created"

    def _placeholder_client(self) -> Client:
        client, _ = Client.objects.get_or_create(
            workspace=self.workspace,
            name=NO_CLIENT_PLACEHOLDER,
            defaults={"status": ClientStatus.ACTIVE},
        )
        return client

    # -- projects ----------------------------------------------------------

    def sync_projects(self, client_conn: ClockifyClient) -> SyncJob:
        job = self._job("project", SyncDirection.BIDIRECTIONAL, is_full=True)
        job.mark_running()
        links = self._links("project")
        client_links = self._links("client")

        remotes = client_conn.iter_pages(lambda p: client_conn.list_projects(page=p))
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
            outcome = self._link_or_create_project(remote, client_links, job=job)
            if outcome == "created":
                job.records_created += 1
            elif outcome == "linked":
                job.records_updated += 1
            else:
                job.records_failed += 1

        self._push_unlinked_projects(client_conn, job)
        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    def _push_unlinked_projects(self, client_conn: ClockifyClient, job: SyncJob) -> None:
        """Outbound: unlinked active local projects get a remote twin."""
        linked_local_ids = {
            link.local_object_id
            for link in ExternalObjectLink.objects.filter(
                workspace=self.workspace, provider=Provider.CLOCKIFY, resource_type="project"
            )
        }
        client_remote_by_local = {
            link.local_object_id: link.external_id for link in self._links("client").values()
        }
        for project in (
            Project.objects.filter(workspace=self.workspace, archived=False)
            .exclude(pk__in=linked_local_ids)
            .select_related("client")
        ):
            job.records_processed += 1
            remote_client_id = client_remote_by_local.get(project.client_id)
            created = client_conn.create_project(
                project_payload_from_project(project, remote_client_id)
            )
            if not created.get("id"):
                job.records_failed += 1
                continue
            self._create_link(
                "project",
                str(created["id"]),
                "projects.Project",
                project.pk,
                normalize_project(created),
            )
            job.records_created += 1

    def _link_or_create_project(
        self,
        remote: dict[str, Any],
        client_links: dict[str, ExternalObjectLink],
        job: SyncJob | None = None,
    ) -> str:
        external_id = str(remote.get("id"))
        name = str(remote.get("name") or "").strip()
        if not name:
            return "failed"
        normalized = normalize_project(remote)

        # Clockify projects may have no client; local ones must. Placeholder.
        remote_client_id = str(remote.get("clientId") or "")
        if remote_client_id:
            client_link = client_links.get(remote_client_id)
            if client_link is None:
                return "failed"
            local_client_id = client_link.local_object_id
        else:
            local_client_id = self._placeholder_client().pk

        linked_ids = ExternalObjectLink.objects.filter(
            workspace=self.workspace, provider=Provider.CLOCKIFY, resource_type="project"
        ).values_list("local_object_id", flat=True)
        matches = list(
            Project.objects.filter(
                workspace=self.workspace,
                client_id=local_client_id,
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
            client_id=local_client_id,
            name=name,
            archived=bool(remote.get("archived", False)),
        )
        self._create_link("project", external_id, "projects.Project", project.pk, normalized)
        return "created"

    # -- tags (↔ service types) --------------------------------------------

    def sync_tags(self, client_conn: ClockifyClient) -> SyncJob:
        job = self._job("tag", SyncDirection.BIDIRECTIONAL, is_full=True)
        job.mark_running()
        links = self._links("tag")

        remotes = client_conn.iter_pages(lambda p: client_conn.list_tags(page=p))
        for remote in remotes:
            name = str(remote.get("name") or "").strip()
            if name.casefold() == BILLED_TAG_NAME.casefold():
                continue  # Coreflow's own marker tag, not a Leistungsart.
            job.records_processed += 1
            external_id = str(remote.get("id"))
            normalized = normalize_tag(remote)
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
                workspace=self.workspace, provider=Provider.CLOCKIFY, resource_type="tag"
            ).values_list("local_object_id", flat=True)
            match = (
                ServiceType.objects.filter(workspace=self.workspace, name__iexact=name)
                .exclude(pk__in=linked_ids)
                .first()
            )
            if match is None:
                match = ServiceType.objects.create(
                    workspace=self.workspace, name=name, active=not bool(remote.get("archived"))
                )
                job.records_created += 1
            else:
                job.records_updated += 1
            self._create_link("tag", external_id, "timetracking.ServiceType", match.pk, normalized)

        self._push_unlinked_tags(client_conn, job)
        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    def _push_unlinked_tags(self, client_conn: ClockifyClient, job: SyncJob) -> None:
        linked_local_ids = {
            link.local_object_id
            for link in ExternalObjectLink.objects.filter(
                workspace=self.workspace, provider=Provider.CLOCKIFY, resource_type="tag"
            )
        }
        for service_type in ServiceType.objects.filter(
            workspace=self.workspace, active=True
        ).exclude(pk__in=linked_local_ids):
            job.records_processed += 1
            created = client_conn.create_tag(tag_payload_from_service_type(service_type))
            if not created.get("id"):
                job.records_failed += 1
                continue
            self._create_link(
                "tag",
                str(created["id"]),
                "timetracking.ServiceType",
                service_type.pk,
                normalize_tag(created),
            )
            job.records_created += 1

    # -- users -------------------------------------------------------------

    def sync_users(self, client_conn: ClockifyClient) -> SyncJob:
        """Match Clockify members to workspace members by e-mail. Never creates."""
        job = self._job("user", SyncDirection.INBOUND, is_full=True)
        job.mark_running()
        links = self._links("user")

        members = {
            membership.user.email.lower(): membership.user
            for membership in WorkspaceMembership.objects.filter(
                workspace=self.workspace
            ).select_related("user")
        }
        remotes = client_conn.iter_pages(lambda p: client_conn.list_users(page=p))
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

    # -- entries: inbound ---------------------------------------------------

    def sync_entries(
        self,
        client_conn: ClockifyClient,
        *,
        since: dt.datetime,
        until: dt.datetime,
        is_full: bool = False,
    ) -> SyncJob:
        job = self._job("entry", SyncDirection.BIDIRECTIONAL, is_full=is_full)
        job.mark_running()

        user_links = self._links("user")
        seen_external: set[str] = set()
        listed_user_ids = [link.local_object_id for link in user_links.values()]

        for user_link in user_links.values():
            window_start = since
            while window_start < until:
                window_end = min(window_start + dt.timedelta(days=FULL_SYNC_WINDOW_DAYS), until)
                remotes = client_conn.iter_pages(
                    lambda p: client_conn.list_time_entries(
                        user_link.external_id,  # noqa: B023 - consumed eagerly
                        start=iso_z(window_start),  # noqa: B023
                        end=iso_z(window_end),  # noqa: B023
                        page=p,
                    )
                )
                for remote in remotes:
                    job.records_processed += 1
                    seen_external.add(str(remote.get("id")))
                    outcome = self.apply_remote_entry(remote, client_conn=client_conn, job=job)
                    if outcome == "created":
                        job.records_created += 1
                    elif outcome in {"updated", "pushed", "merged"}:
                        job.records_updated += 1
                    elif outcome == "failed":
                        job.records_failed += 1
                    else:  # unchanged / skipped_* / conflict
                        job.records_skipped += 1
                job.cursor = {"window_end": iso_z(window_end), "user": user_link.external_id}
                job.save()
                window_start = window_end

        if is_full:
            self._reconcile_window_deletions(since, until, seen_external, listed_user_ids, job)

        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    def apply_remote_entry(
        self,
        remote: dict[str, Any],
        *,
        client_conn: ClockifyClient | None,
        job: SyncJob | None = None,
    ) -> str:
        """Reconcile one remote entry. Returns the outcome for job accounting."""
        if entry_is_running(remote):
            # A running Clockify timer is imported once it stops (TIMER_STOPPED
            # webhook or the next sync window) — the local single-running-timer
            # constraint belongs to local timers.
            return "skipped_running"

        external_id = str(remote.get("id"))
        normalized = normalize_entry(remote)
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type="entry",
            external_id=external_id,
        ).first()
        if link is None:
            return self._adopt_or_create_entry(remote, normalized, client_conn=client_conn)

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
            # Convergent: e.g. our own billed-tag push echoing back. Just adopt
            # the new hash so the next pass is a clean no-op.
            link.mark_synced(normalized)
            return "unchanged"

        if remote_changed and (entry.billing_status in LOCKED_STATUSES or local_changed):
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

        # Local changed, remote unchanged → push back (clockify.md §5).
        if client_conn is None or entry.billing_status in LOCKED_STATUSES:
            return "unchanged"
        payload = self._entry_push_payload(entry, remote)
        remote_after = client_conn.update_time_entry(external_id, payload)
        link.mark_synced(normalize_entry(remote_after) if remote_after.get("id") else normalized)
        return "pushed"

    # -- entries: dedup + creation ------------------------------------------

    def _adopt_or_create_entry(
        self,
        remote: dict[str, Any],
        normalized: dict[str, Any],
        *,
        client_conn: ClockifyClient | None,
    ) -> str:
        refs = self._resolve_entry_refs(remote, client_conn=client_conn)
        if refs == "skipped_no_user":
            return "skipped_no_user"
        if refs == "failed":
            return "failed"
        user, local_client, project, task, service_type = refs

        twin = self._find_local_twin(remote, local_client)
        if twin is not None:
            # The Lexware-dedup rule: one entry, two tags. The local entry keeps
            # every billed fact (status, amounts, invoice links) and simply
            # gains the Clockify identity.
            self._create_link(
                "entry", str(remote["id"]), "timetracking.TimeEntry", twin.pk, normalized
            )
            logger.info(
                "clockify_entry_merged_with_local_twin",
                workspace_id=str(self.workspace.pk),
                entry_id=str(twin.pk),
                clockify_id=str(remote.get("id")),
                twin_source=twin.source,
            )
            return "merged"

        interval = remote.get("timeInterval") or {}
        started_at = parse_iso_z(str(interval["start"]))
        ended_at = parse_iso_z(str(interval["end"]))
        duration = entry_duration_seconds(remote)
        billable = bool(remote.get("billable", True))
        rate = resolve_hourly_rate(
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
                task=task,
                service_type=service_type,
                description=str(remote.get("description") or ""),
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=duration,
                source=EntrySource.CLOCKIFY,
                billable=billable,
                hourly_rate=rate,
                computed_amount=compute_amount(
                    duration_seconds=duration, hourly_rate=rate, billable=billable
                ),
                billing_status=billing_status_for(billable),
            )
            self._create_link(
                "entry", str(remote["id"]), "timetracking.TimeEntry", entry.pk, normalized
            )
        return "created"

    def _resolve_entry_refs(
        self, remote: dict[str, Any], *, client_conn: ClockifyClient | None
    ) -> Any:
        """Resolve (user, client, project, task, service_type) for a remote entry."""
        user_link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type="user",
            external_id=str(remote.get("userId")),
        ).first()
        if user_link is None:
            return "skipped_no_user"
        user = User.objects.filter(pk=user_link.local_object_id).first()
        if user is None:
            return "skipped_no_user"

        project = None
        task = None
        if remote.get("projectId"):
            project = self._local_project_for(str(remote["projectId"]), client_conn)
            if project is None:
                return "failed"
            if remote.get("taskId"):
                task = self._local_task_for(
                    project, str(remote["projectId"]), str(remote["taskId"]), client_conn
                )

        # The client comes through the project; a project-less entry lands on
        # the placeholder (Clockify entries carry no client of their own).
        local_client = project.client if project is not None else self._placeholder_client()

        service_type = None
        for tag_id in remote.get("tagIds") or []:
            tag_link = ExternalObjectLink.objects.filter(
                workspace=self.workspace,
                provider=Provider.CLOCKIFY,
                resource_type="tag",
                external_id=str(tag_id),
            ).first()
            if tag_link is not None:
                service_type = ServiceType.objects.filter(pk=tag_link.local_object_id).first()
                if service_type is not None:
                    break

        return user, local_client, project, task, service_type

    def _local_project_for(
        self, remote_project_id: str, client_conn: ClockifyClient | None
    ) -> Project | None:
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type="project",
            external_id=remote_project_id,
        ).first()
        if link is not None:
            return Project.objects.filter(pk=link.local_object_id).first()
        if client_conn is None:
            return None
        # Never-synced project: pull it (and, transitively, its client) now.
        remote_project = client_conn.get_project(remote_project_id)
        if not remote_project.get("id"):
            return None
        if remote_project.get("clientId"):
            client_link = ExternalObjectLink.objects.filter(
                workspace=self.workspace,
                provider=Provider.CLOCKIFY,
                resource_type="client",
                external_id=str(remote_project["clientId"]),
            ).first()
            if client_link is None:
                remote_client = client_conn.get_client(str(remote_project["clientId"]))
                if remote_client.get("id"):
                    self._link_or_create_client(remote_client)
        self._link_or_create_project(remote_project, self._links("client"))
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type="project",
            external_id=remote_project_id,
        ).first()
        return Project.objects.filter(pk=link.local_object_id).first() if link else None

    def _local_task_for(
        self,
        project: Project,
        remote_project_id: str,
        remote_task_id: str,
        client_conn: ClockifyClient | None,
    ) -> Task | None:
        """Match a Clockify task to a local one by title. Never creates local
        tasks — a local Task needs a board, which Clockify knows nothing about."""
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type="task",
            external_id=remote_task_id,
        ).first()
        if link is not None:
            return Task.objects.filter(pk=link.local_object_id).first()
        if client_conn is None:
            return None
        try:
            remote_task = client_conn.get_task(remote_project_id, remote_task_id)
        except ClockifyError:
            return None
        title = str(remote_task.get("name") or "").strip()
        if not title:
            return None
        match: Task | None = Task.objects.filter(
            workspace=self.workspace, project=project, title__iexact=title
        ).first()
        if match is None:
            return None
        self._create_link(
            "task",
            remote_task_id,
            "projects.Task",
            match.pk,
            {"id": remote_task_id, "name": title},
        )
        return match

    def _find_local_twin(self, remote: dict[str, Any], local_client: Client) -> TimeEntry | None:
        """An existing unlinked local entry that IS this remote entry.

        Tier 1 — exact twin, any source: same client, start within ±60 s, same
        hours at the invoice's 2-decimal precision. Catches history that was
        tracked in both systems before they were connected.

        Tier 2 — Lexware reconstructions: their timestamps are synthetic
        (stacked from 09:00 of the invoice period), so the match is client +
        hours + the remote start falling inside the linked invoice's service
        period. First unconsumed candidate wins; a consumed one carries a link
        and can never match twice.
        """
        interval = remote.get("timeInterval") or {}
        remote_start = parse_iso_z(str(interval["start"]))
        remote_hours = money(seconds_to_hours(entry_duration_seconds(remote)))

        linked_ids = ExternalObjectLink.objects.filter(
            workspace=self.workspace, provider=Provider.CLOCKIFY, resource_type="entry"
        ).values_list("local_object_id", flat=True)

        exact: list[TimeEntry] = list(
            TimeEntry.objects.filter(
                workspace=self.workspace,
                client=local_client,
                ended_at__isnull=False,
                started_at__gte=remote_start - dt.timedelta(seconds=60),
                started_at__lte=remote_start + dt.timedelta(seconds=60),
            )
            .exclude(pk__in=linked_ids)
            .order_by("started_at")
        )
        for candidate in exact:
            if money(seconds_to_hours(candidate.duration_seconds)) == remote_hours:
                return candidate

        reconstructed: list[TimeEntry] = list(
            TimeEntry.objects.filter(
                workspace=self.workspace,
                client=local_client,
                source=EntrySource.LEXWARE,
                ended_at__isnull=False,
            )
            .exclude(pk__in=linked_ids)
            .prefetch_related("invoice_links__invoice")
            .order_by("started_at")
        )
        remote_day = remote_start.astimezone().date()
        for candidate in reconstructed:
            if money(seconds_to_hours(candidate.duration_seconds)) != remote_hours:
                continue
            for invoice_link in candidate.invoice_links.all():
                if invoice_link.invoice_cancelled:
                    continue
                invoice = invoice_link.invoice
                if invoice.period_start is not None and invoice.period_end is not None:
                    if invoice.period_start <= remote_day <= invoice.period_end:
                        return candidate
                    continue
                anchor = invoice.period_end or invoice.invoice_date
                if anchor is not None and remote_day <= anchor:
                    return candidate
        return None

    # -- entries: remote-side edits -----------------------------------------

    def _apply_remote_fields(self, entry: TimeEntry, remote: dict[str, Any]) -> None:
        interval = remote.get("timeInterval") or {}
        started_at = parse_iso_z(str(interval["start"]))
        ended_at = parse_iso_z(str(interval["end"]))
        duration = entry_duration_seconds(remote)
        billable = bool(remote.get("billable", True))

        entry.started_at = started_at
        entry.ended_at = ended_at
        entry.duration_seconds = duration
        entry.description = str(remote.get("description") or "")
        entry.billable = billable
        # Only move along the axis Clockify owns; local workflow states
        # (marked_for_invoice) survive a remote edit that kept billable=true.
        if entry.billing_status not in _COMPATIBLE_STATUSES[billable]:
            entry.billing_status = billing_status_for(billable)
        entry.computed_amount = compute_amount(
            duration_seconds=duration, hourly_rate=entry.hourly_rate, billable=entry.billable
        )
        entry.save()

    def _entry_matches_remote(self, entry: TimeEntry, remote: dict[str, Any]) -> bool:
        """True when local and remote agree on every mirrored field.

        Tags are deliberately not compared: the billed-tag push changes remote
        tagIds without any local counterpart — that echo must read as
        convergence, not drift.
        """
        if entry.ended_at is None:
            return False
        interval = remote.get("timeInterval") or {}
        if not interval.get("end"):
            return False
        started_at = parse_iso_z(str(interval["start"]))
        ended_at = parse_iso_z(str(interval["end"]))
        billable = bool(remote.get("billable", True))
        return (
            entry.started_at == started_at
            and entry.ended_at == ended_at
            and entry.description == str(remote.get("description") or "")
            and entry.billing_status in _COMPATIBLE_STATUSES[billable]
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

    def _entry_push_payload(self, entry: TimeEntry, remote: dict[str, Any]) -> dict[str, Any]:
        """Full PUT payload for a locally edited, linked entry.

        Clockify's PUT replaces: identifiers the local side cannot resolve keep
        their current remote value (an unmapped project must not be cleared),
        and remote tags that are not service-type mappings (e.g. the billed
        tag) are preserved.
        """
        project_id = str(remote.get("projectId") or "") or None
        if entry.project_id is not None:
            project_link = self._link_for_local("project", entry.project_id)
            if project_link is not None:
                project_id = project_link.external_id

        task_id = str(remote.get("taskId") or "") or None
        if entry.task_id is not None:
            task_link = self._link_for_local("task", entry.task_id)
            if task_link is not None:
                task_id = task_link.external_id

        service_tag_ids = {
            link.external_id
            for link in ExternalObjectLink.objects.filter(
                workspace=self.workspace, provider=Provider.CLOCKIFY, resource_type="tag"
            )
        }
        kept = [t for t in (remote.get("tagIds") or []) if str(t) not in service_tag_ids]
        if entry.service_type_id is not None:
            service_link = self._link_for_local("tag", entry.service_type_id)
            if service_link is not None:
                kept.append(service_link.external_id)

        return entry_payload(
            entry, project_id=project_id, task_id=task_id, tag_ids=sorted(set(kept))
        )

    # -- entries: outbound creation -----------------------------------------

    def push_local_entries(
        self, client_conn: ClockifyClient, *, discard_empty: bool = False
    ) -> SyncJob:
        """Create Clockify twins for unlinked local entries (recent window).

        Only manual/timer entries within ``CLOCKIFY_PUSH_LOOKBACK_DAYS`` are
        pushed — the window keeps a fresh connection from dump-loading years of
        history into Clockify. ``discard_empty`` drops the job row when there
        was nothing to do (the beat tick would otherwise pile up no-op rows).
        """
        job = self._job("entry", SyncDirection.OUTBOUND, is_full=False)
        job.mark_running()
        cutoff = timezone.now() - dt.timedelta(days=settings.CLOCKIFY_PUSH_LOOKBACK_DAYS)

        linked_ids = ExternalObjectLink.objects.filter(
            workspace=self.workspace, provider=Provider.CLOCKIFY, resource_type="entry"
        ).values_list("local_object_id", flat=True)
        entries = (
            TimeEntry.objects.filter(
                workspace=self.workspace,
                source__in=PUSHABLE_SOURCES,
                ended_at__isnull=False,
                started_at__gte=cutoff,
            )
            .exclude(pk__in=linked_ids)
            .exclude(billing_status=BillingStatus.CANCELLED)
            .select_related("project", "task", "service_type", "user")
            .order_by("started_at")
        )
        for entry in entries:
            job.records_processed += 1
            outcome = self.push_entry(entry, client_conn)
            if outcome == "created":
                job.records_created += 1
            elif outcome == "failed":
                job.records_failed += 1
            else:
                job.records_skipped += 1

        if discard_empty and job.records_processed == 0:
            job.delete()
            return job
        job.save()
        job.mark_finished(SyncStatus.SUCCESS if job.records_failed == 0 else SyncStatus.PARTIAL)
        return job

    def push_entry(self, entry: TimeEntry, client_conn: ClockifyClient) -> str:
        """Create or update the Clockify twin of one local entry."""
        if entry.ended_at is None or entry.source not in PUSHABLE_SOURCES:
            return "skipped"
        link = self._link_for_local("entry", entry.pk)
        if link is not None:
            # Already linked → the push-back path owns updates.
            remote = client_conn.get_time_entry(link.external_id)
            if not remote.get("id"):
                return "skipped"
            payload = self._entry_push_payload(entry, remote)
            remote_after = client_conn.update_time_entry(link.external_id, payload)
            link.mark_synced(normalize_entry(remote_after))
            return "updated"

        user_link = self._link_for_local("user", entry.user_id)
        if user_link is None:
            return "skipped"  # No Clockify identity for this member.

        project_id = self._ensure_remote_project(entry.project, client_conn)
        task_id = (
            self._ensure_remote_task(entry.task, project_id, client_conn)
            if entry.task is not None and project_id
            else None
        )
        tag_ids: list[str] = []
        service_tag = self._ensure_remote_tag(entry.service_type, client_conn)
        if service_tag:
            tag_ids.append(service_tag)
        if entry.billing_status == BillingStatus.BILLED:
            billed_tag = self._ensure_billed_tag(client_conn)
            if billed_tag:
                tag_ids.append(billed_tag)

        me = self._remote_me_id()
        target_user = None if user_link.external_id == me else user_link.external_id
        created = client_conn.create_time_entry(
            entry_payload(
                entry, project_id=project_id, task_id=task_id, tag_ids=sorted(set(tag_ids))
            ),
            user_id=target_user,
        )
        if not created.get("id"):
            return "failed"
        self._create_link(
            "entry",
            str(created["id"]),
            "timetracking.TimeEntry",
            entry.pk,
            normalize_entry(created),
        )
        return "created"

    def _ensure_remote_project(
        self, project: Project | None, client_conn: ClockifyClient
    ) -> str | None:
        if project is None:
            return None
        link = self._link_for_local("project", project.pk)
        if link is not None:
            return link.external_id
        remote_client_id: str | None = None
        client_link = self._link_for_local("client", project.client_id)
        if client_link is not None:
            remote_client_id = client_link.external_id
        elif project.client.name != NO_CLIENT_PLACEHOLDER:
            created_client = client_conn.create_client(client_payload_from_client(project.client))
            if created_client.get("id"):
                self._create_link(
                    "client",
                    str(created_client["id"]),
                    "crm.Client",
                    project.client_id,
                    normalize_client(created_client),
                )
                remote_client_id = str(created_client["id"])
        created = client_conn.create_project(
            project_payload_from_project(project, remote_client_id)
        )
        if not created.get("id"):
            return None
        self._create_link(
            "project",
            str(created["id"]),
            "projects.Project",
            project.pk,
            normalize_project(created),
        )
        return str(created["id"])

    def _ensure_remote_task(
        self, task: Task | None, project_id: str | None, client_conn: ClockifyClient
    ) -> str | None:
        if task is None or not project_id:
            return None
        link = self._link_for_local("task", task.pk)
        if link is not None:
            return link.external_id
        # Match an existing remote task by name before creating one.
        for remote_task in client_conn.iter_pages(
            lambda p: client_conn.list_tasks(project_id, page=p)
        ):
            if (
                str(remote_task.get("name") or "").strip().casefold()
                == task.title.strip().casefold()
            ):
                self._create_link(
                    "task",
                    str(remote_task["id"]),
                    "projects.Task",
                    task.pk,
                    {"id": str(remote_task["id"]), "name": task.title},
                )
                return str(remote_task["id"])
        created = client_conn.create_task(project_id, task_payload_from_task(task))
        if not created.get("id"):
            return None
        self._create_link(
            "task",
            str(created["id"]),
            "projects.Task",
            task.pk,
            {"id": str(created["id"]), "name": task.title},
        )
        return str(created["id"])

    def _ensure_remote_tag(
        self, service_type: ServiceType | None, client_conn: ClockifyClient
    ) -> str | None:
        if service_type is None:
            return None
        link = self._link_for_local("tag", service_type.pk)
        if link is not None:
            return link.external_id
        created = client_conn.create_tag(tag_payload_from_service_type(service_type))
        if not created.get("id"):
            return None
        self._create_link(
            "tag",
            str(created["id"]),
            "timetracking.ServiceType",
            service_type.pk,
            normalize_tag(created),
        )
        return str(created["id"])

    def _ensure_billed_tag(self, client_conn: ClockifyClient) -> str | None:
        """The workspace tag that marks Coreflow-billed entries in Clockify."""
        if self._billed_tag_id:
            return self._billed_tag_id
        for tag in client_conn.iter_pages(lambda p: client_conn.list_tags(page=p)):
            if str(tag.get("name") or "").casefold() == BILLED_TAG_NAME.casefold():
                self._billed_tag_id = str(tag["id"])
                return self._billed_tag_id
        created = client_conn.create_tag({"name": BILLED_TAG_NAME})
        if created.get("id"):
            self._billed_tag_id = str(created["id"])
        return self._billed_tag_id

    # -- entries: deletion ---------------------------------------------------

    def _reconcile_window_deletions(
        self,
        since: dt.datetime,
        until: dt.datetime,
        seen_external: set[str],
        listed_user_ids: list[Any],
        job: SyncJob,
    ) -> None:
        """Full sync only: linked entries inside the window that the API no
        longer returns were deleted in Clockify. Restricted to users whose
        entries were actually listed — an unlinked user's silence is not
        evidence of deletion."""
        candidate_links = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type="entry",
            deleted_remotely=False,
        ).exclude(external_id__in=seen_external)
        for link in candidate_links:
            entry = TimeEntry.objects.filter(
                workspace=self.workspace,
                pk=link.local_object_id,
                started_at__gte=since,
                started_at__lt=until,
                user_id__in=listed_user_ids,
            ).first()
            if entry is None:
                continue
            self.handle_entry_deleted(link, entry, job=job)

    def handle_entry_deleted(
        self, link: ExternalObjectLink, entry: TimeEntry | None, job: SyncJob | None = None
    ) -> str:
        """Remote entry gone: mirror the deletion, unless local is settled or
        carries Lexware provenance (then only the Clockify tag is dropped)."""
        link.deleted_remotely = True
        link.save(update_fields=["deleted_remotely", "updated_at"])
        if entry is None:
            return "unchanged"
        if entry.billing_status in LOCKED_STATUSES or entry.source == EntrySource.LEXWARE:
            if entry.source == EntrySource.LEXWARE:
                # The entry exists because Lexware billed it; losing its
                # Clockify twin must not delete the billed history. The link
                # row (deleted_remotely=True) simply stops showing the tag.
                return "unchanged"
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

    def push_entry_deletion(self, external_id: str, client_conn: ClockifyClient) -> str:
        """Local entry was deleted → delete the Clockify twin."""
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type="entry",
            external_id=external_id,
        ).first()
        try:
            client_conn.delete_time_entry(external_id)
        except ClockifyError as exc:
            if exc.status_code != 404:  # already gone remotely is success
                raise
        if link is not None:
            link.delete()
        return "deleted"

    # -- single-entity appliers (webhooks) ---------------------------------

    def apply_remote_client(self, remote: dict[str, Any]) -> str:
        external_id = str(remote.get("id"))
        normalized = normalize_client(remote)
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type="client",
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
            provider=Provider.CLOCKIFY,
            resource_type="project",
            external_id=external_id,
        ).first()
        if link is not None:
            if link.payload_changed(normalized):
                link.mark_synced(normalized)
                return "updated"
            return "unchanged"
        return self._link_or_create_project(remote, self._links("client"))

    def apply_remote_tag(self, remote: dict[str, Any]) -> str:
        name = str(remote.get("name") or "").strip()
        if name.casefold() == BILLED_TAG_NAME.casefold():
            return "unchanged"
        external_id = str(remote.get("id"))
        normalized = normalize_tag(remote)
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type="tag",
            external_id=external_id,
        ).first()
        if link is not None:
            if link.payload_changed(normalized):
                link.mark_synced(normalized)
                return "updated"
            return "unchanged"
        if not name:
            return "failed"
        match = ServiceType.objects.filter(workspace=self.workspace, name__iexact=name).first()
        if match is None:
            match = ServiceType.objects.create(workspace=self.workspace, name=name)
        self._create_link("tag", external_id, "timetracking.ServiceType", match.pk, normalized)
        return "created"

    def mark_link_deleted(self, resource_type: str, external_id: str) -> str:
        """client.deleted / project.deleted: flag the link; local CRM objects
        are Coreflow's and are never deleted by a provider."""
        link = ExternalObjectLink.objects.filter(
            workspace=self.workspace,
            provider=Provider.CLOCKIFY,
            resource_type=resource_type,
            external_id=external_id,
        ).first()
        if link is None:
            return "unchanged"
        link.deleted_remotely = True
        link.save(update_fields=["deleted_remotely", "updated_at"])
        return "updated"

    # -- orchestration -----------------------------------------------------

    def full_sync(self, client_conn: ClockifyClient) -> list[SyncJob]:
        """Connect-time / manual full sync: masters first, then entries."""
        now = timezone.now()
        jobs = [
            self.sync_clients(client_conn),
            self.sync_projects(client_conn),
            self.sync_tags(client_conn),
            self.sync_users(client_conn),
            self.sync_entries(
                client_conn,
                since=now - dt.timedelta(days=FULL_SYNC_LOOKBACK_DAYS),
                until=now + dt.timedelta(minutes=5),
                is_full=True,
            ),
            self.push_local_entries(client_conn),
        ]
        logger.info(
            "clockify_full_sync_done",
            workspace_id=str(self.workspace.pk),
            jobs={f"{job.resource_type}:{job.direction}": job.status for job in jobs},
        )
        return jobs

    def incremental_sync(self, client_conn: ClockifyClient) -> SyncJob:
        """Beat tick: masters outbound (cheap no-op when linked), recent
        entries inbound, unlinked recent entries outbound."""
        now = timezone.now()
        outbound = self._job("outbound", SyncDirection.OUTBOUND, is_full=False)
        outbound.mark_running()
        self._push_unlinked_clients(client_conn, outbound)
        self._push_unlinked_projects(client_conn, outbound)
        self._push_unlinked_tags(client_conn, outbound)
        if outbound.records_processed == 0:
            outbound.delete()  # Nothing new locally — keep the job list clean.
        else:
            outbound.save()
            outbound.mark_finished(
                SyncStatus.SUCCESS if outbound.records_failed == 0 else SyncStatus.PARTIAL
            )

        job = self.sync_entries(
            client_conn,
            since=now - dt.timedelta(days=INCREMENTAL_LOOKBACK_DAYS),
            until=now + dt.timedelta(minutes=5),
            is_full=False,
        )
        self.push_local_entries(client_conn, discard_empty=True)
        return job


def entry_links_for(entry_ids: list[Any], workspace: Workspace) -> dict[Any, str]:
    """Map local TimeEntry ids → Clockify entry ids, for the billed push."""
    return {
        link.local_object_id: link.external_id
        for link in ExternalObjectLink.objects.filter(
            workspace=workspace,
            provider=Provider.CLOCKIFY,
            resource_type="entry",
            local_object_id__in=entry_ids,
            deleted_remotely=False,
        )
    }


def push_entries_billed(workspace: Workspace, entry_ids: list[Any]) -> int:
    """Tag every linked entry of a billed invoice with the billed tag.

    Clockify has no billed *state*, so the fact is mirrored as a workspace tag
    (:data:`BILLED_TAG_NAME`). Per-entry GET+PUT keeps every other remote field
    exactly as it is — PUT replaces, so the payload is rebuilt from the current
    remote entry, not from local state.
    """
    links = entry_links_for(entry_ids, workspace)
    if not links:
        return 0
    sync = ClockifySync(workspace, trigger="billed_push")
    pushed = 0
    with ClockifyClient() as client_conn:
        billed_tag = sync._ensure_billed_tag(client_conn)
        if not billed_tag:
            return 0
        for local_id, external_id in links.items():
            remote = client_conn.get_time_entry(external_id)
            if not remote.get("id") or entry_is_running(remote):
                continue
            tag_ids = {str(t) for t in (remote.get("tagIds") or [])}
            if billed_tag in tag_ids:
                pushed += 1
                continue
            tag_ids.add(billed_tag)
            interval = remote.get("timeInterval") or {}
            remote_after = client_conn.update_time_entry(
                external_id,
                {
                    "start": interval.get("start"),
                    "end": interval.get("end"),
                    "billable": bool(remote.get("billable", True)),
                    "description": remote.get("description") or "",
                    "projectId": remote.get("projectId"),
                    "taskId": remote.get("taskId"),
                    "tagIds": sorted(tag_ids),
                },
            )
            link = ExternalObjectLink.objects.get(
                workspace=workspace,
                provider=Provider.CLOCKIFY,
                resource_type="entry",
                local_object_id=local_id,
            )
            if remote_after.get("id"):
                link.mark_synced(normalize_entry(remote_after))
            pushed += 1
    logger.info("clockify_billed_pushed", workspace_id=str(workspace.pk), count=pushed)
    return pushed


def compute_remote_entry_hash(remote: dict[str, Any]) -> str:
    """Convenience for tests: hash exactly as the sync does."""
    return compute_sync_hash(normalize_entry(remote))
