from django.urls import path

from . import views


app_name = "carrito"


urlpatterns = [

    path(
        "",
        views.detalle_carrito,
        name="detalle",
    ),

    path(
        "agregar/<int:presentacion_id>/",
        views.agregar_al_carrito,
        name="agregar",
    ),

    path(
        "agregar-combo/<int:combo_id>/",
        views.agregar_combo,
        name="agregar_combo",
    ),

    path(
        "actualizar/<int:item_id>/",
        views.actualizar_item,
        name="actualizar",
    ),

    path(
        "eliminar/<int:item_id>/",
        views.eliminar_item,
        name="eliminar",
    ),

    path(
        "vaciar/",
        views.vaciar_carrito,
        name="vaciar",
    ),
]