"""Webhook endpoints — mounted at /webhooks/, outside the session-auth API."""

from __future__ import annotations

from django.urls import path

from apps.integrations.webhooks import ClockodoWebhookView

app_name = "webhooks"

urlpatterns = [
    path("clockodo/", ClockodoWebhookView.as_view(), name="clockodo"),
]
