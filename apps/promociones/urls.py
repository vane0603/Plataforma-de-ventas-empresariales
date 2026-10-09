from django.urls import path

from . import views


app_name = "combos"


urlpatterns = [

    path(
        "",
        views.lista_combos,
        name="lista_combos",
    ),

    path(
        "<int:pk>/",
        views.detalle_combo,
        name="detalle_combo",
    ),

]