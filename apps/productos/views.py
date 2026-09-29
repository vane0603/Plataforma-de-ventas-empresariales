from django.shortcuts import get_object_or_404, render

from apps.catalogos.models import Categoria
from .models import Producto


def lista_productos(request):
    productos = (
        Producto.objects
        .filter(activo=True)
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
        )
    )

    categorias = (
        Categoria.objects
        .filter(activo=True)
        .order_by(
            "orden",
            "nombre",
        )
    )

    return render(
        request,
        "productos/lista_general.html",
        {
            "productos": productos,
            "categorias": categorias,
        },
    )


def productos_por_categoria(request, categoria_id):
    categoria = get_object_or_404(
        Categoria,
        id=categoria_id,
        activo=True,
    )

    productos = (
        Producto.objects
        .filter(
            categoria=categoria,
            activo=True,
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
        )
    )

    return render(
        request,
        "productos/lista.html",
        {
            "categoria": categoria,
            "productos": productos,
        },
    )


def detalle_producto(request, pk):
    producto = get_object_or_404(
        Producto.objects
        .select_related(
            "categoria",
            "marca",
        )
        .prefetch_related(
            "presentaciones__presentacion__unidad",
        ),
        pk=pk,
        activo=True,
    )

    presentaciones = producto.presentaciones.filter(
        activo=True
    )

    return render(
        request,
        "productos/detalle.html",
        {
            "producto": producto,
            "presentaciones": presentaciones,
        },
    )