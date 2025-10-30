import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import door_access.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'door_access_system.settings')

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AuthMiddlewareStack(
        URLRouter(
            door_access.routing.websocket_urlpatterns
        )
    ),
})
