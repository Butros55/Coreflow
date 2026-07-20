"""Domain exceptions and the DRF exception handler.

Error responses share one envelope so the frontend can render them generically:

    {"error": {"code": "...", "message": "...", "detail": {...}, "request_id": "..."}}

Unexpected exceptions never leak an internal message to the client — they are
logged with the request ID and reported as a generic 500.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.core.logging import get_logger

logger = get_logger("core.exceptions")


class CoreflowError(APIException):
    """Base for domain errors carrying a stable machine-readable code.

    ``default_detail`` strings are user-facing (the SPA toasts them verbatim)
    and therefore German.
    """

    # Annotated as int, not left to inference: mypy would otherwise infer
    # Literal[400] here and reject every subclass that sets a different status.
    status_code: int = status.HTTP_400_BAD_REQUEST
    default_code: str = "coreflow_error"
    default_detail: str = "Eine Geschäftsregel wurde verletzt."


class InvalidCredentials(CoreflowError):
    """Login failed.

    Deliberately one error for every cause — unknown email, wrong password,
    inactive account. A distinguishable response is an account-enumeration
    oracle. Raised as its own class (rather than a ValidationError with a code
    kwarg) because DRF drops the code when the detail is a dict, which would
    flatten this to a generic "invalid".
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_credentials"
    default_detail = "E-Mail-Adresse oder Passwort ist falsch."


class BusinessRuleViolation(CoreflowError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "business_rule_violation"
    default_detail = "Die Aktion verletzt eine Geschäftsregel."


class TimerAlreadyRunning(BusinessRuleViolation):
    default_code = "timer_already_running"
    default_detail = "Es läuft bereits ein Timer. Bitte zuerst stoppen."


class TimeEntryAlreadyBilled(BusinessRuleViolation):
    default_code = "time_entry_already_billed"
    default_detail = "Dieser Zeiteintrag ist bereits einer Rechnung zugeordnet."


class IntegrationDisabled(CoreflowError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "integration_disabled"
    default_detail = (
        "Diese Integration ist deaktiviert. Bitte zuerst in den Einstellungen aktivieren."
    )


class IntegrationNotConfigured(CoreflowError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "integration_not_configured"
    default_detail = "Für diese Integration fehlen Zugangsdaten."


class ProviderError(CoreflowError):
    """An external provider returned an error we could not recover from."""

    # Re-annotated for the same reason as the base: a bare assignment would
    # re-narrow this to Literal[502] and break the subclasses below.
    status_code: int = status.HTTP_502_BAD_GATEWAY
    default_code = "provider_error"
    default_detail = "Der externe Anbieter hat einen Fehler gemeldet."


class ProviderRateLimited(ProviderError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "provider_rate_limited"
    default_detail = "Der externe Anbieter hat die Anfrage wegen zu vieler Zugriffe abgelehnt."


class ProviderUnavailable(ProviderError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "provider_unavailable"
    default_detail = "Der externe Anbieter ist gerade nicht erreichbar."


class SyncConflictDetected(BusinessRuleViolation):
    default_code = "sync_conflict"
    default_detail = (
        "Lokale und externe Daten weichen voneinander ab. Bitte den Konflikt zuerst lösen."
    )


def _extract_code(exc: Exception, response_data: Any) -> str:
    if isinstance(exc, APIException):
        code = getattr(exc, "default_code", None)
        detail = getattr(exc, "detail", None)
        detail_code = getattr(detail, "code", None)
        return str(detail_code or code or "error")
    return "error"


def coreflow_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Normalise every error into the Coreflow envelope."""
    if isinstance(exc, DjangoValidationError):
        exc = _to_drf_validation_error(exc)
    if isinstance(exc, PermissionDenied):
        from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied

        exc = DRFPermissionDenied(str(exc) or None)
    if isinstance(exc, Http404):
        from rest_framework.exceptions import NotFound

        exc = NotFound()

    response = drf_exception_handler(exc, context)
    request = context.get("request")
    request_id = getattr(request, "request_id", None)

    if response is None:
        # Not a DRF exception: something genuinely unexpected. Log the detail,
        # return an opaque body — internal messages can carry table names,
        # file paths, or fragments of customer data.
        logger.exception(
            "unhandled_exception",
            exc_type=type(exc).__name__,
            path=getattr(request, "path", None),
            request_id=request_id,
        )
        return Response(
            {
                "error": {
                    "code": "internal_error",
                    "message": "Ein interner Fehler ist aufgetreten. Bitte erneut versuchen.",
                    "request_id": request_id,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = response.data
    message: str
    payload: dict[str, Any] | None = None

    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message = str(detail["detail"])
    elif isinstance(detail, dict):
        message = _validation_message(detail)
        payload = detail
    elif isinstance(detail, list):
        message = _validation_message({"non_field_errors": detail})
        payload = {"non_field_errors": detail}
    else:
        message = str(detail)

    response.data = {
        "error": {
            "code": _extract_code(exc, detail),
            "message": message,
            "request_id": request_id,
            **({"detail": payload} if payload else {}),
        }
    }
    return response


def _first_message(value: Any) -> str | None:
    """Depth-first first human-readable string in a DRF error structure."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        for nested in value.values():
            found = _first_message(nested)
            if found:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            found = _first_message(item)
            if found:
                return found
        return None
    return str(value) if value is not None else None


def _validation_message(payload: dict[str, Any]) -> str:
    """A concrete, human-readable summary instead of a bare "Validation failed".

    Field messages themselves are already localised (LANGUAGE_CODE=de); this
    surfaces the first one so a plain toast is useful even before a form
    renders the per-field details from ``detail``.
    """
    first = _first_message(payload)
    if first is None:
        return "Eingaben ungültig — bitte prüfen."
    field_count = len(payload)
    if field_count > 1:
        return f"{first} (+{field_count - 1} weitere Felder)"
    return first


def _to_drf_validation_error(exc: DjangoValidationError) -> APIException:
    from rest_framework.exceptions import ValidationError as DRFValidationError

    if hasattr(exc, "message_dict"):
        return DRFValidationError(exc.message_dict)
    return DRFValidationError(exc.messages)
