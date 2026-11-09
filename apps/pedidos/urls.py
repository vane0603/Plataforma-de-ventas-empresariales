from django.urls import path
from . import views, views_entregas, views_reportes, views_siigo

app_name = "pedidos"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("confirmacion/<int:pedido_id>/", views.confirmacion, name="confirmacion"),
    path("<int:pedido_id>/pagar-saldo/", views.pagar_saldo, name="pagar_saldo"),
    path("<int:pedido_id>/cancelar/", views.cancelar, name="cancelar"),
    path("seguimiento/<uuid:codigo>/", views.seguimiento, name="seguimiento"),
    path("mis-pedidos/", views.mis_pedidos, name="mis_pedidos"),
    path("reporte/", views_reportes.reporte_pedidos, name="reporte"),
    path("reporte/siigo/", views_siigo.exportar_siigo, name="siigo"),

    # Entregas (repartidores)
    path("entregas/", views_entregas.entregas_lista, name="entregas"),
    path("entregas/despachar/", views_entregas.entregas_despachar, name="entregas_despachar"),
    path("entregas/<int:pedido_id>/", views_entregas.entrega_registrar, name="entrega_registrar"),
    path("entregas/<int:pedido_id>/constancia/", views_entregas.entrega_constancia, name="entrega_constancia"),
    path("entregas/<int:pedido_id>/firma.png", views_entregas.entrega_firma, name="entrega_firma"),
]
