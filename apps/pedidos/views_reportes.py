from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import render

from .models import Pedido
from .reportes import TIPO_XLSX, Filtros, generar_xlsx, pedidos_del_reporte, resumen

PERMISO = "pedidos.view_pedido"
MAX_VISTA_PREVIA = 50


@login_required
@permission_required(PERMISO, raise_exception=True)
def reporte_pedidos(request):
    """Vista previa con filtros y descarga del mismo listado en Excel (?formato=xlsx)."""
    filtros = Filtros.desde_peticion(request.GET)
    pedidos = pedidos_del_reporte(filtros) if not filtros.errores else Pedido.objects.none()

    if request.GET.get("formato") == "xlsx" and not filtros.errores:
        respuesta = HttpResponse(generar_xlsx(pedidos), content_type=TIPO_XLSX)
        respuesta["Content-Disposition"] = f'attachment; filename="{filtros.nombre_archivo()}"'
        return respuesta

    parametros = request.GET.copy()
    parametros.pop("formato", None)
    parametros["formato"] = "xlsx"
    return render(request, "pedidos/reporte_pedidos.html", {
        "filtros": filtros,
        "pedidos": pedidos[:MAX_VISTA_PREVIA],
        "max_vista_previa": MAX_VISTA_PREVIA,
        "resumen": resumen(pedidos),
        "estados": Pedido.ESTADOS,
        "metodos": Pedido.METODOS_PAGO,
        "tipos": Pedido.TIPOS_ENTREGA,
        "url_excel": "?" + parametros.urlencode(),
    })
