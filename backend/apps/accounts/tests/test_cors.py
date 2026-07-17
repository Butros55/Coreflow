"""CORS preflight tests.

These exist because of a real bug: the SPA sends ``X-Workspace-ID``, which is a
non-simple header, so the browser preflights it. django-cors-headers only
advertises a fixed default allow-list, which does not include it — so the
preflight returned 200 while the *actual* request was blocked with an opaque
``net::ERR_FAILED``.

curl cannot catch this (it never preflights) and neither can a normal DRF test
(the test client ignores CORS). Only a real browser surfaced it, so the contract
is pinned here instead.
"""

from __future__ import annotations

import pytest
from django.http import HttpResponseBase
from django.test import Client
from django.urls import reverse

from apps.accounts.permissions import WORKSPACE_HEADER

pytestmark = pytest.mark.django_db

ORIGIN = "http://localhost:3000"


def _preflight(client: Client, path: str, request_headers: str) -> HttpResponseBase:
    return client.options(
        path,
        HTTP_ORIGIN=ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS=request_headers,
    )


class TestCorsPreflight:
    def test_workspace_header_is_allowed(self, client: Client) -> None:
        """The header the whole tenancy model depends on must survive preflight."""
        response = _preflight(client, reverse("auth:session"), WORKSPACE_HEADER.lower())

        assert response.status_code == 200
        allowed = response.headers.get("access-control-allow-headers", "").lower()
        assert WORKSPACE_HEADER.lower() in allowed

    def test_csrf_header_is_allowed(self, client: Client) -> None:
        """Every write sends X-CSRFToken; without this, no mutation works."""
        response = _preflight(client, reverse("auth:login"), "x-csrftoken,content-type")

        allowed = response.headers.get("access-control-allow-headers", "").lower()
        assert "x-csrftoken" in allowed
        assert "content-type" in allowed

    def test_credentials_are_allowed(self, client: Client) -> None:
        """Session auth is cookie-based: without this the cookie is never sent."""
        response = _preflight(client, reverse("auth:session"), WORKSPACE_HEADER.lower())
        assert response.headers.get("access-control-allow-credentials") == "true"

    def test_allowed_origin_is_echoed(self, client: Client) -> None:
        response = _preflight(client, reverse("auth:session"), "content-type")
        assert response.headers.get("access-control-allow-origin") == ORIGIN

    def test_unknown_origin_is_not_allowed(self, client: Client) -> None:
        response = client.options(
            reverse("auth:session"),
            HTTP_ORIGIN="https://evil.example.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
        )
        # With credentials allowed, echoing an arbitrary origin would let any
        # site read the user's data.
        assert response.headers.get("access-control-allow-origin") != "https://evil.example.com"

    def test_request_id_is_exposed_to_javascript(self, client: Client) -> None:
        """Cross-origin response headers are hidden from JS unless exposed."""
        response = client.get(reverse("core:liveness"), HTTP_ORIGIN=ORIGIN)
        exposed = response.headers.get("access-control-expose-headers", "").lower()
        assert "x-request-id" in exposed
