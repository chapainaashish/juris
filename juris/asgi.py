import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "juris.settings")
django.setup()

from asgi_middleware_static_file import ASGIMiddlewareStaticFile
from channels.routing import ProtocolTypeRouter, URLRouter
from django.conf import settings
from django.core.asgi import get_asgi_application
from django.urls import path
from django_channels_jwt.middleware import JwtAuthMiddlewareStack

from subscriptions.consumers import NotificationConsumer

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]

application = get_asgi_application()
application = ASGIMiddlewareStaticFile(
    application,
    static_url=settings.STATIC_URL,
    static_root_paths=[settings.STATIC_ROOT],
)

application = ProtocolTypeRouter(
    {
        "http": application,
        "websocket": JwtAuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
