from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.fondos.models import Finca, FondoEmpleado

from .acceso import filtro_pedidos_accesibles
from .entregas import (
    EntregaError,
    decodificar_firma,
    despachar_pedidos,
    pedidos_por_entregar,
    puede_ver_entrega,
    registrar_entrega,
)
from .models import Pedido

PERMISO = "pedidos.registrar_entrega"


def _fecha(texto):
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


@permission_required(PERMISO, raise_exception=True)
def entregas_lista(request):
    """Dos pestañas: pedidos por entregar y pedidos ya entregados."""
    vista = "entregados" if request.GET.get("vista") == "entregados" else "pendientes"
    busqueda = request.GET.get("q", "").strip()
    fondo = request.GET.get("fondo", "")
    finca = request.GET.get("finca", "")
    despacho = request.GET.get("despacho", "")
    desde, hasta = _fecha(request.GET.get("desde")), _fecha(request.GET.get("hasta"))

    pendientes = pedidos_por_entregar()
    entregados = Pedido.objects.filter(entrega__isnull=False)

    def filtrar(pedidos):
        if busqueda:
            pedidos = pedidos.filter(
                Q(numero__icontains=busqueda)
                | Q(nombre_contacto__icontains=busqueda)
                | Q(usuario__first_name__icontains=busqueda)
                | Q(usuario__last_name__icontains=busqueda)
                | Q(solicitud_nomina__nombre_completo__icontains=busqueda)
                | Q(entrega__recibido_por__icontains=busqueda)
            )
        if fondo.isdigit():
            pedidos = pedidos.filter(solicitud_nomina__fondo_id=fondo)
        if finca.isdigit():
            pedidos = pedidos.filter(solicitud_nomina__finca_id=finca)
        return pedidos

    if vista == "entregados":
        pedidos = filtrar(entregados)
        if desde:
            pedidos = pedidos.filter(entrega__entregado_en__date__gte=desde)
        if hasta:
            pedidos = pedidos.filter(entrega__entregado_en__date__lte=hasta)
        pedidos = pedidos.select_related("entrega", "entrega__entregado_por").order_by("-entrega__entregado_en")
    else:
        pedidos = filtrar(pendientes)
        if despacho == "por_despachar":
            pedidos = pedidos.filter(despachado_en__isnull=True)
        elif despacho == "en_camino":
            pedidos = pedidos.filter(despachado_en__isnull=False)
        pedidos = pedidos.order_by("solicitud_nomina__finca__nombre", "created_at")

    pedidos = pedidos.select_related("usuario", "solicitud_nomina__fondo", "solicitud_nomina__finca")
    pagina = Paginator(pedidos, 30).get_page(request.GET.get("page"))

    return render(request, "pedidos/entregas_lista.html", {
        "vista": vista,
        "pedidos": pagina,
        "pagina": pagina,
        "busqueda": busqueda,
        "fondo": fondo,
        "finca": finca,
        "despacho": despacho,
        "desde": request.GET.get("desde", "") if desde else "",
        "hasta": request.GET.get("hasta", "") if hasta else "",
        "total_pendientes": pendientes.count(),
        "total_en_camino": pendientes.filter(despachado_en__isnull=False).count(),
        "total_entregados": entregados.count(),
        "entregados_hoy": entregados.filter(entrega__entregado_en__date=timezone.localdate()).count(),
        "fondos": FondoEmpleado.objects.filter(activo=True).order_by("nombre"),
        "fincas": Finca.objects.filter(activo=True).select_related("fondo").order_by("fondo__nombre", "nombre"),
    })


@require_POST
@permission_required(PERMISO, raise_exception=True)
def entregas_despachar(request):
    """Marca como "En camino" uno o varios pedidos y avisa a cada comprador."""
    ids = [int(valor) for valor in request.POST.getlist("pedidos") if valor.isdigit()]
    if not ids:
        messages.warning(request, "Selecciona al menos un pedido para despachar.")
    else:
        despachados = despachar_pedidos(ids, usuario=request.user)
        if despachados:
            numeros = ", ".join(p.numero for p in despachados[:5]) + ("…" if len(despachados) > 5 else "")
            messages.success(
                request,
                f"{len(despachados)} pedido(s) en camino: {numeros}. Se avisó a cada cliente.",
            )
        if len(despachados) < len(ids):
            messages.info(request, "Algunos pedidos ya estaban en camino o ya no están por entregar.")

    volver = request.POST.get("volver", "")
    if url_has_allowed_host_and_scheme(volver, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(volver)
    return redirect("pedidos:entregas")


@permission_required(PERMISO, raise_exception=True)
def entrega_registrar(request, pedido_id):
    pedido = get_object_or_404(
        Pedido.objects.select_related("solicitud_nomina__finca", "solicitud_nomina__fondo").prefetch_related("items"),
        id=pedido_id,
    )
    if hasattr(pedido, "entrega"):
        messages.info(request, f"El pedido {pedido.numero} ya fue entregado.")
        return redirect("pedidos:entrega_constancia", pedido_id=pedido.id)

    solicitud = getattr(pedido, "solicitud_nomina", None)
    sugerido = solicitud.nombre_completo if solicitud else pedido.nombre_cliente
    datos = {"recibido_por": sugerido, "observaciones": ""}
    error = None

    if request.method == "POST":
        datos = {
            "recibido_por": request.POST.get("recibido_por", ""),
            "observaciones": request.POST.get("observaciones", ""),
        }
        try:
            firma = decodificar_firma(request.POST.get("firma", ""))
            registrar_entrega(
                pedido,
                recibido_por=datos["recibido_por"],
                firma_png=firma,
                observaciones=datos["observaciones"],
                usuario=request.user,
            )
        except EntregaError as exc:
            error = str(exc)
        else:
            messages.success(request, f"Entrega del pedido {pedido.numero} registrada.")
            return redirect("pedidos:entregas")

    return render(request, "pedidos/entrega_registrar.html", {
        "pedido": pedido,
        "solicitud": solicitud,
        "datos": datos,
        "error": error,
    })


def _pedido_con_entrega_visible(request, pedido_id):
    pedido = get_object_or_404(
        Pedido.objects.select_related("entrega", "usuario", "solicitud_nomina__finca", "solicitud_nomina__fondo"),
        id=pedido_id,
        entrega__isnull=False,
    )
    en_sesion = Pedido.objects.filter(filtro_pedidos_accesibles(request), pk=pedido.pk).exists()
    if not (puede_ver_entrega(request.user, pedido) or en_sesion):
        raise Http404
    return pedido


def entrega_constancia(request, pedido_id):
    pedido = _pedido_con_entrega_visible(request, pedido_id)
    return render(request, "pedidos/entrega_constancia.html", {
        "pedido": pedido,
        "entrega": pedido.entrega,
        "solicitud": getattr(pedido, "solicitud_nomina", None),
    })


def entrega_firma(request, pedido_id):
    """La firma no está en /media/: solo se entrega a quien tiene acceso al pedido."""
    pedido = _pedido_con_entrega_visible(request, pedido_id)
    if not pedido.entrega.firma:
        raise Http404
    respuesta = FileResponse(pedido.entrega.firma.open("rb"), content_type="image/png")
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta
