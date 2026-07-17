"""Shared Django settings for Coreflow.

Conventions that hold across the whole codebase:

* Primary keys are UUIDs (see ``apps.core.models.UUIDModel``).
* Money is ``Decimal`` — never float. See ``apps.core.money``.
* Timestamps are stored in UTC; ``TIME_ZONE`` only affects presentation and the
  boundaries of "day"/"month" style reports.
* Secrets come from the environment, never from source.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from environs import Env

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent

env = Env()
# Read the repo-root .env when present. In Docker the values arrive as real
# environment variables instead, and `recurse=False` keeps this predictable.
env.read_env(str(REPO_ROOT / ".env"), recurse=False)

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
APP_ENV = env.str("APP_ENV", "development")
DEBUG = env.bool("DJANGO_DEBUG", default=False)

# No default in production — prod.py asserts a real value is present.
SECRET_KEY = env.str("SECRET_KEY", "insecure-dev-key-do-not-use-in-production")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", ["localhost", "127.0.0.1", "backend"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", ["http://localhost:3000"])

APP_URL = env.str("APP_URL", "http://localhost:3000")
API_URL = env.str("API_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "django_celery_beat",
    "django_celery_results",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.crm",
    "apps.projects",
    "apps.timetracking",
    "apps.invoicing",
    "apps.finance",
    "apps.scheduling",
    "apps.files",
    "apps.integrations",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django_structlog.middlewares.RequestMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": env.dj_db_url(
        "DATABASE_URL",
        default="postgresql://coreflow:coreflow@localhost:5432/coreflow",
        conn_max_age=env.int("DB_CONN_MAX_AGE", 60),
    )
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Argon2 first: better resistance to GPU cracking than PBKDF2.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

LOGIN_URL = "/admin/login/"

# Admin is a break-glass tool. The path is configurable so production can move it
# off the well-known default that every scanner probes.
ADMIN_URL = env.str("ADMIN_URL", "admin/")
ADMIN_ENABLED = env.bool("ADMIN_ENABLED", True)

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "de-de"
TIME_ZONE = env.str("TIME_ZONE", "Europe/Berlin")
USE_I18N = True
USE_TZ = True  # Always store UTC; render in TIME_ZONE.

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Object storage. When OBJECT_STORAGE_ENDPOINT is unset we fall back to the local
# filesystem so the app boots with zero external credentials (demo mode).
OBJECT_STORAGE_ENDPOINT = env.str("OBJECT_STORAGE_ENDPOINT", "")
OBJECT_STORAGE_ACCESS_KEY = env.str("OBJECT_STORAGE_ACCESS_KEY", "")
OBJECT_STORAGE_SECRET_KEY = env.str("OBJECT_STORAGE_SECRET_KEY", "")
OBJECT_STORAGE_BUCKET = env.str("OBJECT_STORAGE_BUCKET", "coreflow")
OBJECT_STORAGE_REGION = env.str("OBJECT_STORAGE_REGION", "us-east-1")

_use_object_storage = bool(OBJECT_STORAGE_ENDPOINT and OBJECT_STORAGE_ACCESS_KEY)

STORAGES: dict[str, dict[str, Any]] = {
    "default": (
        {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "endpoint_url": OBJECT_STORAGE_ENDPOINT,
                "access_key": OBJECT_STORAGE_ACCESS_KEY,
                "secret_key": OBJECT_STORAGE_SECRET_KEY,
                "bucket_name": OBJECT_STORAGE_BUCKET,
                "region_name": OBJECT_STORAGE_REGION,
                "file_overwrite": False,
                "default_acl": None,
                "querystring_auth": True,
                "querystring_expire": 900,
                "addressing_style": "path",
            },
        }
        if _use_object_storage
        else {"BACKEND": "django.core.files.storage.FileSystemStorage"}
    ),
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Upload guard rails (enforced in apps.files validators, not just advisory).
FILE_UPLOAD_MAX_BYTES = env.int("FILE_UPLOAD_MAX_BYTES", 25 * 1024 * 1024)
FILE_UPLOAD_ALLOWED_EXTENSIONS = env.list(
    "FILE_UPLOAD_ALLOWED_EXTENSIONS",
    [
        "pdf",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "svg",
        "txt",
        "md",
        "csv",
        "xlsx",
        "xls",
        "docx",
        "doc",
        "pptx",
        "odt",
        "ods",
        "zip",
        "json",
        "xml",
        "ics",
    ],
)
DATA_UPLOAD_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_BYTES
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# ---------------------------------------------------------------------------
# Sessions / CSRF / cookies
# ---------------------------------------------------------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_NAME = "coreflow_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", 60 * 60 * 24 * 14)
SESSION_SAVE_EVERY_REQUEST = True

CSRF_COOKIE_NAME = "coreflow_csrftoken"
# Readable by JS on purpose: the SPA echoes it back in the X-CSRFToken header.
# This is the standard Django double-submit pattern and is not a session token.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", ["http://localhost:3000"])
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.SessionAuthentication401",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "apps.accounts.permissions.IsWorkspaceMember",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "apps.core.exceptions.coreflow_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "login": env.str("THROTTLE_LOGIN", "10/min"),
        "webhook": env.str("THROTTLE_WEBHOOK", "120/min"),
        "sync": env.str("THROTTLE_SYNC", "20/min"),
        "export": env.str("THROTTLE_EXPORT", "30/min"),
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "COERCE_DECIMAL_TO_STRING": True,  # Keep Decimal exact over the wire.
}

if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ]

SPECTACULAR_SETTINGS = {
    "TITLE": "Coreflow API",
    "DESCRIPTION": (
        "Central business management system: CRM, projects, time tracking, "
        "invoicing, finance forecasting, and Lexware/Clockodo integration."
    ),
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "ENUM_NAME_OVERRIDES": {
        "BillingStatusEnum": "apps.timetracking.models.BillingStatus.choices",
        "WorkspaceRoleEnum": "apps.accounts.models.WorkspaceRole.choices",
    },
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
REDIS_URL = env.str("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "django-cache"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", 30 * 60)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", 25 * 60)
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_RESULT_EXTENDED = True
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "coreflow",
    }
}

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
EMAIL_HOST = env.str("EMAIL_HOST", "")
EMAIL_PORT = env.int("EMAIL_PORT", 1025)
EMAIL_HOST_USER = env.str("EMAIL_USER", "")
EMAIL_HOST_PASSWORD = env.str("EMAIL_PASSWORD", "")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", False)
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", "coreflow@localhost")
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend"
)

# ---------------------------------------------------------------------------
# Demo seed (seed_demo refuses to run when APP_ENV=production)
# ---------------------------------------------------------------------------
DEMO_USER_EMAIL = env.str("DEMO_USER_EMAIL", "demo@coreflow.local")
DEMO_USER_PASSWORD = env.str("DEMO_USER_PASSWORD", "coreflow-demo-1234")

# ---------------------------------------------------------------------------
# Business defaults
# ---------------------------------------------------------------------------
DEFAULT_CURRENCY = env.str("DEFAULT_CURRENCY", "EUR")
DEFAULT_HOURLY_RATE = env.str("DEFAULT_HOURLY_RATE", "95.00")
DEFAULT_PAYMENT_TERM_DAYS = env.int("DEFAULT_PAYMENT_TERM_DAYS", 14)
# Rounding applied to time entries: increment in minutes, 0 = no rounding.
TIME_ROUNDING_INCREMENT_MINUTES = env.int("TIME_ROUNDING_INCREMENT_MINUTES", 0)
TIME_ROUNDING_STRATEGY = env.str("TIME_ROUNDING_STRATEGY", "nearest")  # nearest|up|down

# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------
LEXWARE_ENABLED = env.bool("LEXWARE_ENABLED", False)
LEXWARE_API_BASE_URL = env.str("LEXWARE_API_BASE_URL", "https://api.lexware.io")
LEXWARE_API_KEY = env.str("LEXWARE_API_KEY", "")
LEXWARE_WEBHOOK_PUBLIC_URL = env.str("LEXWARE_WEBHOOK_PUBLIC_URL", "")
LEXWARE_WEBHOOK_SECRET = env.str("LEXWARE_WEBHOOK_SECRET", "")
LEXWARE_SYNC_INTERVAL_MINUTES = env.int("LEXWARE_SYNC_INTERVAL_MINUTES", 30)
# Deliberately defaults to False: invoices are created as drafts and a human
# finalises them in Lexware. Flipping this issues legally binding documents.
LEXWARE_CREATE_FINAL_INVOICES = env.bool("LEXWARE_CREATE_FINAL_INVOICES", False)
LEXWARE_TIMEOUT_SECONDS = env.float("LEXWARE_TIMEOUT_SECONDS", 30.0)
LEXWARE_MAX_RETRIES = env.int("LEXWARE_MAX_RETRIES", 4)

CLOCKODO_ENABLED = env.bool("CLOCKODO_ENABLED", False)
CLOCKODO_API_BASE_URL = env.str("CLOCKODO_API_BASE_URL", "https://my.clockodo.com/api")
CLOCKODO_API_USER = env.str("CLOCKODO_API_USER", "")
CLOCKODO_API_KEY = env.str("CLOCKODO_API_KEY", "")
CLOCKODO_EXTERNAL_APP_NAME = env.str("CLOCKODO_EXTERNAL_APP_NAME", "Coreflow")
CLOCKODO_EXTERNAL_APP_EMAIL = env.str("CLOCKODO_EXTERNAL_APP_EMAIL", "")
CLOCKODO_WEBHOOK_TOKEN = env.str("CLOCKODO_WEBHOOK_TOKEN", "")
CLOCKODO_SYNC_INTERVAL_MINUTES = env.int("CLOCKODO_SYNC_INTERVAL_MINUTES", 15)
CLOCKODO_TIMEOUT_SECONDS = env.float("CLOCKODO_TIMEOUT_SECONDS", 30.0)
CLOCKODO_MAX_RETRIES = env.int("CLOCKODO_MAX_RETRIES", 4)

# ---------------------------------------------------------------------------
# Security headers (tightened further in prod.py)
# ---------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:", "blob:"],
        "font-src": ["'self'", "data:"],
        "connect-src": ["'self'"],
        "frame-ancestors": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "object-src": ["'none'"],
    }
}

# ---------------------------------------------------------------------------
# Data retention (German commercial/tax law: §147 AO, §257 HGB → 10 years)
# ---------------------------------------------------------------------------
RETENTION_INVOICE_YEARS = env.int("RETENTION_INVOICE_YEARS", 10)
RETENTION_AUDIT_LOG_DAYS = env.int("RETENTION_AUDIT_LOG_DAYS", 365 * 3)
RETENTION_WEBHOOK_EVENT_DAYS = env.int("RETENTION_WEBHOOK_EVENT_DAYS", 90)
RETENTION_SYNC_JOB_DAYS = env.int("RETENTION_SYNC_JOB_DAYS", 90)

# ---------------------------------------------------------------------------
# Logging (structlog; secrets are scrubbed by apps.core.logging processors)
# ---------------------------------------------------------------------------
LOG_LEVEL = env.str("LOG_LEVEL", "INFO")
LOG_JSON = env.bool("LOG_JSON", not DEBUG)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "structlog.stdlib.ProcessorFormatter",
            "processor": "structlog.processors.JSONRenderer",
            "foreign_pre_chain": [
                "structlog.stdlib.add_log_level",
                "structlog.processors.TimeStamper",
            ],
        },
        "console": {
            "()": "structlog.stdlib.ProcessorFormatter",
            "processor": "structlog.dev.ConsoleRenderer",
        },
        "plain": {"format": "%(asctime)s %(levelname)-8s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "django.request": {"level": "ERROR", "handlers": ["console"], "propagate": False},
        "coreflow": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
        "coreflow.integrations": {
            "level": env.str("LOG_LEVEL_INTEGRATIONS", LOG_LEVEL),
            "handlers": ["console"],
            "propagate": False,
        },
        "celery": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
}

DJANGO_STRUCTLOG_CELERY_ENABLED = True

# Token lifetime for signed download URLs handed to the browser.
FILE_DOWNLOAD_URL_TTL = timedelta(minutes=15)
