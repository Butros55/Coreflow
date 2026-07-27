"""Request-scoped middleware."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import structlog
from django.http import HttpRequest, HttpResponse

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware:
    """Attach a request ID to every request, log context, and response.

    Honours an inbound ``X-Request-ID`` so a reverse proxy's ID survives into our
    logs, but validates it as a UUID first — otherwise the header is an
    unbounded attacker-controlled string that lands straight in the log stream.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = self._resolve_request_id(request)
        request.request_id = request_id  # type: ignore[attr-defined]

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = self.get_response(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

        response[REQUEST_ID_HEADER] = request_id
        return response

    @staticmethod
    def _resolve_request_id(request: HttpRequest) -> str:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        if incoming:
            try:
                return str(uuid.UUID(incoming))
            except ValueError:
                pass  # Untrusted value: fall through and mint our own.
        return str(uuid.uuid4())
