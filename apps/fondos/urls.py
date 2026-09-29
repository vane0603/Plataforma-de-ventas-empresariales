from django.urls import path
from . import views

app_name = "fondos"

urlpatterns = [
    path("solicitar/<int:pedido_id>/", views.solicitar_descuento_nomina, name="solicitar_descuento_nomina"),
    path("solicitud/<int:solicitud_id>/exitosa/", views.solicitud_exitosa, name="solicitud_exitosa"),
    path("mis-solicitudes/", views.mis_solicitudes, name="mis_solicitudes"),
    path("solicitud/<int:solicitud_id>/", views.detalle_solicitud, name="detalle_solicitud"),
    path("gestion/", views.gestion_solicitudes, name="gestion_solicitudes"),
    path("gestion/<int:solicitud_id>/", views.gestion_detalle, name="gestion_detalle"),
]
