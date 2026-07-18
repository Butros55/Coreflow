"""Appointment serializers."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.core.api import WorkspaceScopedSerializer
from apps.scheduling.models import Appointment


class AppointmentSerializer(WorkspaceScopedSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True, default=None)
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    participant_details = UserSerializer(source="participants", many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "client",
            "client_name",
            "project",
            "project_name",
            "title",
            "description",
            "starts_at",
            "ends_at",
            "location",
            "video_link",
            "participants",
            "participant_details",
            "status",
            "status_display",
            "reminder_minutes_before",
            "outcome_notes",
            "next_steps",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        starts = attrs.get("starts_at") or (self.instance.starts_at if self.instance else None)
        ends = attrs.get("ends_at") or (self.instance.ends_at if self.instance else None)
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "Ende muss nach dem Beginn liegen."})
        return attrs
