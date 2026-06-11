from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

from subscriptions.webhook import stripe_webhook

schema_view = get_schema_view(
    openapi.Info(
        title="Juris API",
        default_version="v1",
        description="API documentation for Juris",
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/user/", include("users.urls")),
    path("api/profiles/", include("profiles.urls")),
    path("api/subscription/", include("subscriptions.urls")),
    path("api/lawyer/appointment/", include("lawyer_appointment.urls")),
    path("api/lawyer/wallet/", include("lawyer_wallet.urls")),
    path("api/lawyer/", include("lawyer.urls")),
    path("api/lawyer/", include("lawyer_availability.urls")),
    path("api/kyc/", include("kyc.urls")),
    path("stripe/webhook/", stripe_webhook, name="stripe-webhook"),
    re_path(
        r"^swagger(?P<format>\.json|\.yaml)$",
        schema_view.without_ui(cache_timeout=0),
        name="schema-json",
    ),
    path(
        "swagger/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
