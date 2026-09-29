from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "cuenta/login/",
        auth_views.LoginView.as_view(template_name="seguridad/login.html"),
        name="login",
    ),
    path("cuenta/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.dashboard.urls")),
    path("productos/", include("apps.productos.urls")),
    path("carrito/", include("apps.carrito.urls")),
    path("combos/", include("apps.promociones.urls")),
    path("pedidos/", include("apps.pedidos.urls")),
    path("fondos/", include("apps.fondos.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
