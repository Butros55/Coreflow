"""Authentication for the SPA.

Coreflow uses Django session cookies rather than JWTs held in JavaScript. The
session cookie is ``HttpOnly``, so an XSS bug cannot exfiltrate it, and CSRF is
handled by Django's double-submit token. A token in ``localStorage`` would trade
that away for no benefit here — the frontend and API are same-site.
"""

from __future__ import annotations

from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request


class SessionAuthentication401(SessionAuthentication):
    """Session auth that answers 401 (not 403) when nobody is logged in.

    DRF returns 403 for unauthenticated requests when no authentication class
    exposes a ``WWW-Authenticate`` header. That makes "you are not logged in"
    indistinguishable from "you are logged in but lack rights" — the SPA needs
    to tell those apart to decide between redirecting to login and showing a
    permission error. Returning a header flips the unauthenticated case to 401.

    CSRF is still enforced on unsafe methods by the parent class.
    """

    def authenticate_header(self, request: Request) -> str:
        return 'Session realm="coreflow"'
