"""Production settings.

This module deliberately fails loudly at import time rather than booting with an
insecure default. A misconfigured production process should never start.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from config.settings.base import *
from config.settings.base import APP_URL, LOGGING, SECRET_KEY, env

DEBUG = False
APP_ENV = "production"

_INSECURE_KEY_MARKERS = ("insecure", "dev-only", "change-me", "test-only")

if not SECRET_KEY or any(marker in SECRET_KEY.lower() for marker in _INSECURE_KEY_MARKERS):
    raise ImproperlyConfigured(
        "SECRET_KEY must be set to a strong, unique value in production. "
        "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
    )

if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("SECRET_KEY must be at least 50 characters in production.")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must list explicit hostnames in production.")

if not APP_URL.startswith("https://"):
    raise ImproperlyConfigured("APP_URL must use https:// in production.")

# ---------------------------------------------------------------------------
# Transport security
# ---------------------------------------------------------------------------
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", 60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# ---------------------------------------------------------------------------
# Logging: JSON to stdout for the log shipper, secrets scrubbed upstream.
# ---------------------------------------------------------------------------
LOGGING = {
    **LOGGING,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
}

# Fail fast when a required integration is switched on without credentials —
# a silently non-syncing production instance is worse than a refused boot.
if env.bool("LEXWARE_ENABLED", False) and not env.str("LEXWARE_API_KEY", ""):
    raise ImproperlyConfigured("LEXWARE_ENABLED=true requires LEXWARE_API_KEY.")

if env.bool("CLOCKIFY_ENABLED", False) and not env.str("CLOCKIFY_API_KEY", ""):
    raise ImproperlyConfigured("CLOCKIFY_ENABLED=true requires CLOCKIFY_API_KEY.")
