"""Test settings — fast, hermetic, and never touching a real external API.

Every integration is force-disabled here. A test that wants provider behaviour
must opt in explicitly (see ``apps/integrations/tests/conftest.py``) and stub the
HTTP layer with respx. There is no code path in the suite that can reach the
real Lexware or Clockodo API.
"""

from __future__ import annotations

from config.settings.base import *
from config.settings.base import REST_FRAMEWORK, env

DEBUG = False
APP_ENV = "test"

SECRET_KEY = "test-only-secret-key-not-used-anywhere-else"  # noqa: S105

# Hashing dominates auth test time otherwise.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

DATABASES = {
    "default": env.dj_db_url(
        "DATABASE_URL",
        default="postgresql://coreflow:coreflow@localhost:5432/coreflow",
    )
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["TEST"] = {"NAME": "coreflow_test"}

# Run tasks inline so workflows are assertable without a broker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
SESSION_ENGINE = "django.contrib.sessions.backends.db"

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# In-memory storage so uploads never touch the disk during tests. (A too-small
# FileField max_length once made this look broken; the field is now 500 chars,
# ample for the nested-UUID key.)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Integrations off by default — tests must opt in and mock.
LEXWARE_ENABLED = False
CLOCKODO_ENABLED = False
LEXWARE_API_KEY = ""
CLOCKODO_API_USER = ""
CLOCKODO_API_KEY = ""
LEXWARE_WEBHOOK_SECRET = "test-webhook-secret"  # noqa: S105
CLOCKODO_WEBHOOK_TOKEN = "test-webhook-token"  # noqa: S105

# Retries make failure-path tests slow and flaky; exercise backoff explicitly instead.
LEXWARE_MAX_RETRIES = 0
CLOCKODO_MAX_RETRIES = 0

# Throttling off unless a test enables it. The scopes must stay declared with an
# explicit None — ScopedRateThrottle raises ImproperlyConfigured for an *unknown*
# scope, whereas a None rate short-circuits allow_request() to True.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        "login": None,
        "webhook": None,
        "sync": None,
        "export": None,
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
}
