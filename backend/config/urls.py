"""Root URL configuration.

Everything the SPA consumes lives under ``/api/v1/``. Infrastructure probes are
mounted at the root so orchestrators can hit ``/healthz`` without an API prefix.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    # Infrastructure
    path("", include("apps.core.urls")),
    # API
    path("api/v1/", include("config.api_urls")),
    # OpenAPI schema + docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # Django admin — a break-glass tool, not the product surface.
    path(settings.ADMIN_URL, admin.site.urls),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    try:
        import debug_toolbar  # noqa: F401

        urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]
    except ImportError:  # pragma: no cover - toolbar is a dev-only extra
        pass
