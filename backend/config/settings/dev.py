"""Development settings — never use for production."""

from __future__ import annotations

from config.settings.base import *
from config.settings.base import INSTALLED_APPS, MIDDLEWARE, env

DEBUG = True
APP_ENV = "development"

ALLOWED_HOSTS = ["*"]

# Convenience only: in dev we tolerate a generated key, prod.py refuses to.
SECRET_KEY = env.str("SECRET_KEY", "django-insecure-dev-only-key-change-me")

INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    *MIDDLEWARE,
]

INTERNAL_IPS = ["127.0.0.1", "localhost"]
# Docker: the gateway IP is not predictable, so let the toolbar decide via callback.
DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG}

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Next.js dev server needs to talk to the API and hot-reload over ws://.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", "'unsafe-eval'", "'unsafe-inline'"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:", "blob:"],
        "font-src": ["'self'", "data:"],
        "connect-src": ["'self'", "ws:", "http://localhost:3000", "http://localhost:8000"],
        "frame-ancestors": ["'none'"],
    }
}
