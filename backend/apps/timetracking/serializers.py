"""Time tracking serializers."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone
from rest_framework import serializers

from apps.core.api import WorkspaceScopedSerializer
from apps.timetracking.models import BillingStatus, EntrySource, ServiceType, TimeEntry
from apps.timetracking.services import compute_amount, resolve_hourly_rate

# States in which an entry is locked against edits that would change its value —
# it is already on (or past) an invoice.
LOCKED_STATUSES = {BillingStatus.DRAFT_CREATED, BillingStatus.BILLED}


class ServiceTypeSerializer(WorkspaceScopedSerializer):
    class Meta:
        model = ServiceType
        fields = [
            "id",
            "name",
            "description",
            "default_hourly_rate",
            "default_invoice_text",
            "active",
        ]
        read_only_fields = ["id"]

    def validate_name(self, value: str) -> str:
        """Catch duplicates here — the DB unique constraint alone would surface
        as an opaque 500 because ``workspace`` is not a serializer field and
        DRF therefore cannot auto-generate the unique-together validator."""
        from apps.accounts.permissions import resolve_workspace

        value = value.strip()
        request = self.context.get("request")
        workspace = resolve_workspace(request) if request is not None else None
        if workspace is not None:
            clash = ServiceType.objects.filter(workspace=workspace, name__iexact=value)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    "Eine Leistungsart mit diesem Namen existiert bereits."
                )
        return value


class TimeEntrySerializer(WorkspaceScopedSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    task_title = serializers.CharField(source="task.title", read_only=True, default=None)
    service_type_name = serializers.CharField(
        source="service_type.name", read_only=True, default=None
    )
    is_running = serializers.BooleanField(read_only=True)
    # The active (non-cancelled) invoice this entry is billed on, if any —
    # including whether the link came from the local composer or was matched
    # by the Lexware import.
    invoice_link = serializers.SerializerMethodField()
    # Optional convenience on create: duration instead of ended_at.
    duration_input_seconds = serializers.IntegerField(write_only=True, required=False, min_value=60)

    class Meta:
        model = TimeEntry
        fields = [
            "id",
            "user",
            "client",
            "client_name",
            "project",
            "project_name",
            "phase",
            "task",
            "task_title",
            "service_type",
            "service_type_name",
            "description",
            "started_at",
            "ended_at",
            "duration_seconds",
            "duration_input_seconds",
            "source",
            "billable",
            "hourly_rate",
            "computed_amount",
            "billing_status",
            "rounded_from_seconds",
            "is_running",
            "invoice_link",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "duration_seconds",
            "source",
            "computed_amount",
            "rounded_from_seconds",
            "invoice_link",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "hourly_rate": {"required": False},
            "billing_status": {"required": False},
        }

    def get_invoice_link(self, obj: TimeEntry) -> dict[str, Any] | None:
        links = getattr(obj, "active_invoice_links", None)
        if links is None:  # list views prefetch; single-object paths fall back
            links = list(
                obj.invoice_links.filter(invoice_cancelled=False).select_related("invoice")
            )
        if not links:
            return None
        link = links[0]
        return {
            "invoice_id": str(link.invoice_id),
            "invoice_number": link.invoice.invoice_number,
            "source": link.source,
        }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance: TimeEntry | None = self.instance

        if instance is not None and instance.billing_status in LOCKED_STATUSES:
            raise serializers.ValidationError(
                "Dieser Eintrag ist bereits abgerechnet und kann nicht mehr geändert werden."
            )

        # Task implies project and client; fill them in rather than trusting the
        # client to send a consistent triple.
        task = attrs.get("task")
        if task is not None:
            attrs["project"] = task.project
            attrs["client"] = task.project.client

        project = attrs.get("project") or (instance.project if instance else None)
        client = attrs.get("client") or (instance.client if instance else None)
        if project is not None and client is not None and project.client_id != client.pk:
            raise serializers.ValidationError({"project": "Projekt gehört nicht zu diesem Kunden."})

        started = attrs.get("started_at") or (instance.started_at if instance else None)
        ended = attrs.get("ended_at", instance.ended_at if instance else None)
        duration_input = attrs.pop("duration_input_seconds", None)

        if self.instance is None:
            # Manual entries are complete intervals; running entries are created
            # only through the timer endpoint, which owns the uniqueness rules.
            if ended is None and duration_input is None:
                raise serializers.ValidationError(
                    {"ended_at": "Endzeit oder Dauer angeben (Timer über /timer/start)."}
                )
            if ended is None and duration_input is not None and started is not None:
                ended = started + timedelta(seconds=duration_input)
                attrs["ended_at"] = ended

        if started is not None and ended is not None and ended <= started:
            raise serializers.ValidationError(
                {"ended_at": "Endzeit muss nach der Startzeit liegen."}
            )
        if started is not None and started > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError({"started_at": "Startzeit liegt in der Zukunft."})
        return attrs

    def _finalise(self, attrs: dict[str, Any], instance: TimeEntry | None) -> dict[str, Any]:
        """Compute duration, rate snapshot, amount and billing status."""
        request = self.context["request"]
        workspace = attrs.get("workspace") or (instance.workspace if instance else None)
        client = attrs.get("client") or (instance.client if instance else None)
        project = (
            attrs.get("project") if "project" in attrs else (instance.project if instance else None)
        )
        service_type = (
            attrs.get("service_type")
            if "service_type" in attrs
            else (instance.service_type if instance else None)
        )

        started = attrs.get("started_at") or (instance.started_at if instance else None)
        ended = attrs.get("ended_at", instance.ended_at if instance else None)
        if started is not None and ended is not None:
            attrs["duration_seconds"] = int((ended - started).total_seconds())

        explicit_rate = attrs.get("hourly_rate") or (instance.hourly_rate if instance else None)
        # The viewset stamps workspace into save(); on update it comes from the
        # instance. Either way it exists by the time _finalise runs.
        assert workspace is not None
        rate = resolve_hourly_rate(
            workspace=workspace,
            client=client,
            project=project,
            service_type=service_type,
            explicit=explicit_rate,
        )
        attrs["hourly_rate"] = rate

        billable = attrs.get("billable", instance.billable if instance else True)
        duration = attrs.get("duration_seconds", instance.duration_seconds if instance else 0)
        attrs["computed_amount"] = compute_amount(
            duration_seconds=duration, hourly_rate=rate, billable=billable
        )

        # billing_status follows billable unless explicitly set to a later state.
        current_status = attrs.get("billing_status", instance.billing_status if instance else None)
        if current_status in (None, BillingStatus.OPEN, BillingStatus.NOT_BILLABLE):
            attrs["billing_status"] = BillingStatus.OPEN if billable else BillingStatus.NOT_BILLABLE
        _ = request  # context is part of the contract; silence unused warnings
        return attrs

    def create(self, validated_data: dict[str, Any]) -> TimeEntry:
        validated_data = self._finalise(validated_data, None)
        validated_data.setdefault("source", EntrySource.MANUAL)
        created: TimeEntry = super().create(validated_data)
        return created

    def update(self, instance: TimeEntry, validated_data: dict[str, Any]) -> TimeEntry:
        validated_data = self._finalise(validated_data, instance)
        updated: TimeEntry = super().update(instance, validated_data)
        return updated


class TimerStartSerializer(serializers.Serializer[dict[str, Any]]):
    client = serializers.UUIDField(required=False, allow_null=True)
    project = serializers.UUIDField(required=False, allow_null=True)
    task = serializers.UUIDField(required=False, allow_null=True)
    service_type = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=500, default=""
    )
    billable = serializers.BooleanField(default=True)
