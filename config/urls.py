from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path
from django.views.generic import TemplateView
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

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
    path("cuenta/", include("apps.cuentas.urls")),
    path(
        "politica-de-datos/",
        TemplateView.as_view(template_name="legal/politica_datos.html"),
        name="politica_datos",
    ),
    path("", include("apps.dashboard.urls")),
    path("productos/", include("apps.productos.urls")),
    path("carrito/", include("apps.carrito.urls")),
    path("combos/", include("apps.promociones.urls")),
    path("pedidos/", include("apps.pedidos.urls")),
    path("fondos/", include("apps.fondos.urls")),
    path("pagos/", include("apps.pagos.urls")),

    # API REST v1 + documentación interactiva
    path("api/v1/", include("apps.api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api_schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api_schema"), name="api_docs"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVIR_MEDIA:
    # Producción en Windows con Waitress (ver despliegue/windows).
    urlpatterns += [re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})]
