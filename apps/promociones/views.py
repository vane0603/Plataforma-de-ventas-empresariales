from django.shortcuts import get_object_or_404, render

from .models import Combo


def lista_combos(request):

    combos = (
        Combo.objects
        .filter(
            activo=True,
        )
        .order_by(
            "-destacado",
            "orden",
            "nombre",
        )
    )

    return render(
        request,
        "combos/index.html",
        {
            "combos": combos,
        },
    )


def detalle_combo(request, pk):

    combo = get_object_or_404(
        Combo,
        pk=pk,
        activo=True,
    )

    return render(
        request,
        "combos/detalle.html",
        {
            "combo": combo,
        },
    )