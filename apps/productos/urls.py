from django.urls import path

from . import views


app_name = "productos"


urlpatterns = [

    path(
        "",
        views.lista_productos,
        name="lista",
    ),

    path(
        "categoria/<int:categoria_id>/",
        views.productos_por_categoria,
        name="categoria",
    ),

    path(
        "<int:pk>/",
        views.detalle_producto,
        name="detalle",
    ),

]