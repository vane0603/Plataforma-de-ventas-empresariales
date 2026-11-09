from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from .reportes import TIPO_XLSX
from .siigo import SiigoError, fondos_con_siigo, generar_xlsx, nombre_archivo, numerar, pedidos_del_fondo, revisar


def _fecha(texto, defecto):
    try:
        return date.fromisoformat(texto) if texto else defecto
    except ValueError:
        return defecto


def _archivo(pedidos, config, desde, hasta):
    respuesta = HttpResponse(generar_xlsx(pedidos, config, desde, hasta), content_type=TIPO_XLSX)
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre_archivo(config, desde, hasta)}"'
    return respuesta


@login_required
@permission_required("pedidos.view_pedido", raise_exception=True)
def exportar_siigo(request):
    """
    Facturas para Siigo de los fondos configurados (p. ej. MACS).
    GET: lista los pedidos aprobados en el rango. POST: descarga los pedidos marcados, numerados
    desde el número de factura inicial que escribe el usuario. Se puede repetir cuantas veces se quiera.
    """
    datos = request.POST if request.method == "POST" else request.GET
    configuraciones = list(fondos_con_siigo())
    config = next((c for c in configuraciones if str(c.pk) == datos.get("fondo")), configuraciones[0] if configuraciones else None)
    hoy = timezone.localdate()
    desde = _fecha(datos.get("desde"), hoy.replace(day=1))
    hasta = _fecha(datos.get("hasta"), hoy)
    if desde > hasta:
        desde, hasta = hasta, desde

    if config is None:
        return render(request, "pedidos/siigo.html", {"configuraciones": []})

    revision = revisar(pedidos_del_fondo(config, desde, hasta))
    volver = f"{request.path}?fondo={config.pk}&desde={desde}&hasta={hasta}"

    if request.method == "POST":
        if not request.user.has_perm("pedidos.change_pedido"):
            raise PermissionDenied
        marcados = set(request.POST.getlist("pedidos"))
        elegidos = [p for p in revision.pedidos if str(p.pk) in marcados]
        if not elegidos:
            messages.warning(request, "Marca al menos un pedido para descargar.")
            return redirect(volver)
        numero = datos.get("numero_inicial", "").strip()
        try:
            numerar(config, elegidos, int(numero) if numero.isdigit() else None)
        except SiigoError as exc:
            messages.error(request, str(exc))
            return redirect(volver)
        return _archivo(elegidos, config, desde, hasta)

    return render(request, "pedidos/siigo.html", {
        "configuraciones": configuraciones,
        "config": config,
        "desde": desde,
        "hasta": hasta,
        "revision": revision,
        "puede_generar": request.user.has_perm("pedidos.change_pedido"),
    })
