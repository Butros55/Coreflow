"""Health and readiness probes."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from django.db.utils import OperationalError
from django.urls import reverse
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


class TestLiveness:
    def test_liveness_is_public(self, api_client: APIClient) -> None:
        response = api_client.get(reverse("core:liveness"))
        assert response.status_code == 200
        assert response.data["status"] == "ok"

    def test_probes_are_exempt_from_atomic_requests(self) -> None:
        """Probes must not be wrapped in a transaction.

        ATOMIC_REQUESTS=True opens a transaction before the view body runs. That
        would make liveness 500 during a database outage — restart-looping every
        container over a dependency failure — and would pre-empt readiness'
        deliberate 503. Both must be able to answer *about* the database without
        needing it.
        """
        from django.urls import resolve

        for path in ("/healthz", "/readyz", "/version"):
            view = resolve(path).func
            non_atomic: set[str] = getattr(view, "_non_atomic_requests", set())
            assert "default" in non_atomic, f"{path} is not exempt from ATOMIC_REQUESTS"

    def test_liveness_performs_no_real_queries(
        self, api_client: APIClient, django_assert_num_queries: Any
    ) -> None:
        """Liveness checks nothing but itself."""
        with django_assert_num_queries(0):
            response = api_client.get(reverse("core:liveness"))
        assert response.status_code == 200


class TestReadiness:
    def test_readiness_reports_ok_when_dependencies_are_up(self, api_client: APIClient) -> None:
        response = api_client.get(reverse("core:readiness"))
        assert response.status_code == 200
        assert response.data["status"] == "ok"
        assert response.data["checks"]["database"]["status"] == "ok"
        assert response.data["checks"]["cache"]["status"] == "ok"

    def test_readiness_reports_integration_flags(self, api_client: APIClient) -> None:
        response = api_client.get(reverse("core:readiness"))
        integrations = response.data["checks"]["integrations"]
        # Test settings force both off.
        assert integrations["lexware"] == "disabled"
        assert integrations["clockodo"] == "disabled"

    def test_readiness_returns_503_when_the_database_is_down(self, api_client: APIClient) -> None:
        with patch("apps.core.health.connections") as mock_conn:
            mock_conn.__getitem__.return_value.cursor.side_effect = OperationalError("down")
            response = api_client.get(reverse("core:readiness"))
        assert response.status_code == 503
        assert response.data["status"] == "degraded"

    def test_readiness_does_not_leak_internal_error_detail(self, api_client: APIClient) -> None:
        """A probe endpoint is unauthenticated — it must not narrate internals."""
        with patch("apps.core.health.connections") as mock_conn:
            mock_conn.__getitem__.return_value.cursor.side_effect = OperationalError(
                "password authentication failed for user 'coreflow' at 10.0.0.5:5432"
            )
            response = api_client.get(reverse("core:readiness"))
        body = str(response.data)
        assert "password" not in body
        assert "10.0.0.5" not in body


class TestVersion:
    def test_version_is_public_and_reports_environment(self, api_client: APIClient) -> None:
        response = api_client.get(reverse("core:version"))
        assert response.status_code == 200
        assert response.data["service"] == "coreflow-backend"
        assert response.data["time_zone"] == "Europe/Berlin"
