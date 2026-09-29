from django.shortcuts import render

from apps.catalogos.models import Categoria
from apps.productos.models import Producto
from apps.promociones.models import Combo


def dashboard(request):

    categorias = (
        Categoria.objects
        .filter(activo=True)
        .order_by(
            "orden",
            "nombre",
        )
    )

    productos_destacados = (
        Producto.objects
        .filter(
            activo=True,
            destacado=True,
        )
        .select_related(
            "categoria",
            "marca",
        )
        .prefetch_related(
            "presentaciones",
        )
        .order_by(
            "orden",
            "nombre",
        )[:8]
    )

    combos_destacados = (
        Combo.objects
        .filter(
            activo=True,
            destacado=True,
        )
        .order_by(
            "orden",
            "nombre",
        )[:4]
    )

    return render(
        request,
        "home/index.html",
        {
            "categorias": categorias,
            "productos_destacados": productos_destacados,
            "combos_destacados": combos_destacados,
        },
    )