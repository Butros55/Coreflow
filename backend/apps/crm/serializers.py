"""CRM serializers."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.core.api import WorkspaceScopedSerializer
from apps.crm.models import Client, ClientActivity, ClientContact, ClientNote


class ClientContactSerializer(WorkspaceScopedSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = ClientContact
        fields = [
            "id",
            "client",
            "first_name",
            "last_name",
            "full_name",
            "position",
            "email",
            "phone",
            "mobile",
            "preferred_channel",
            "is_primary",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # "Make primary" must demote the previous primary, not explode on the
        # partial unique index. Handled here (single UPDATE) rather than in save.
        if attrs.get("is_primary"):
            client = attrs.get("client") or (self.instance.client if self.instance else None)
            if client is not None:
                qs = ClientContact.objects.filter(client=client, is_primary=True)
                if self.instance is not None:
                    qs = qs.exclude(pk=self.instance.pk)
                qs.update(is_primary=False)
        return attrs


class ClientNoteSerializer(WorkspaceScopedSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = ClientNote
        fields = [
            "id",
            "client",
            "author",
            "content",
            "note_type",
            "follow_up_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "author", "created_at", "updated_at"]


class ClientActivitySerializer(WorkspaceScopedSerializer):
    actor = UserSerializer(read_only=True)
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)

    class Meta:
        model = ClientActivity
        fields = [
            "id",
            "client",
            "event_type",
            "event_type_display",
            "description",
            "occurred_at",
            "actor",
            "project",
            "note",
        ]
        read_only_fields = fields


class ClientSerializer(WorkspaceScopedSerializer):
    """Full client, plus list-view aggregates injected via serializer context.

    The aggregates come from grouped queries in the viewset (three GROUP BYs for
    the whole page) rather than per-row annotations: combining Sum/Count across
    several joins multiplies rows and silently inflates the numbers.
    """

    primary_contact = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id",
            "name",
            "short_name",
            "legal_form",
            "client_number",
            "status",
            "industry",
            "website",
            "email",
            "phone",
            "billing_street",
            "billing_zip",
            "billing_city",
            "billing_country_code",
            "shipping_street",
            "shipping_zip",
            "shipping_city",
            "shipping_country_code",
            "tax_number",
            "vat_id",
            "default_hourly_rate",
            "payment_term_days",
            "currency",
            "notes",
            "tags",
            "acquisition_source",
            "customer_since",
            "archived",
            "primary_contact",
            "stats",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "client_number", "created_at", "updated_at"]

    def get_primary_contact(self, obj: Client) -> dict[str, Any] | None:
        # Prefetched as `primary_contacts`; falls back to None cleanly.
        contacts = getattr(obj, "primary_contacts", None)
        if not contacts:
            return None
        contact = contacts[0]
        return {
            "id": str(contact.pk),
            "full_name": contact.full_name,
            "email": contact.email,
            "phone": contact.phone or contact.mobile,
        }

    def get_stats(self, obj: Client) -> dict[str, Any]:
        stats: dict[str, dict[str, Any]] = self.context.get("client_stats", {})
        return stats.get(
            str(obj.pk),
            {
                "active_projects": 0,
                "open_seconds": 0,
                "open_amount": "0.00",
                "last_activity_at": None,
            },
        )
