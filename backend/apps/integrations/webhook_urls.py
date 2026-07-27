"""Webhook endpoints — mounted at /webhooks/, outside the session-auth API."""

from __future__ import annotations

from django.urls import path

from apps.integrations.webhooks import ClockifyWebhookView

app_name = "webhooks"

urlpatterns = [
    path("clockify/", ClockifyWebhookView.as_view(), name="clockify"),
]
