from django.urls import path
from . import views

app_name = "pedidos"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("confirmacion/<int:pedido_id>/", views.confirmacion, name="confirmacion"),
    path("mis-pedidos/", views.mis_pedidos, name="mis_pedidos"),
]
