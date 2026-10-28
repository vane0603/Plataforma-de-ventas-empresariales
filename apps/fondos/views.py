from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.cifrado import huella
from apps.pedidos.models import Pedido
from .forms import CargaPadronForm, RespuestaFondoForm, SolicitudDescuentoNominaForm
from .models import FondoEmpleado, SolicitudDescuentoNomina
from .reportes import (
    ReporteError,
    archivo_reporte,
    cerrar_corte,
    enviar_corte_por_correo,
    periodo_desde_texto,
    periodo_por_defecto,
    resumen,
    solicitudes_del_periodo,
)
from .services import (
    DecisionInvalida,
    SolicitudError,
    aplicar_decision,
    crear_solicitud,
    importar_padron,
)


def datos_iniciales_solicitud(usuario, pedido):
    """
    Precarga el formulario con lo que ya se conoce del comprador: su última solicitud
    (si no fue anonimizada) y el celular que escribió en el checkout de este pedido.
    """
    inicial = {
        "nombre_completo": usuario.get_full_name() or usuario.username,
        "correo": usuario.email,
    }
    anterior = (
        SolicitudDescuentoNomina.objects
        .filter(usuario=usuario, anonimizada_en__isnull=True)
        .select_related("fondo", "finca")
        .order_by("-fecha_solicitud")
        .first()
    )
    if anterior is not None:
        for campo in ("nombre_completo", "correo", "documento", "telefono", "empresa", "numero_afiliado"):
            valor = getattr(anterior, campo)
            if valor:
                inicial[campo] = valor
        if anterior.fondo.activo:
            inicial["fondo"] = anterior.fondo_id
            if anterior.finca_id and anterior.finca.activo:
                inicial["finca"] = anterior.finca_id
    # El celular de este pedido es el dato más reciente.
    if pedido.telefono_contacto:
        inicial["telefono"] = pedido.telefono_contacto
    return inicial


@login_required
def solicitar_descuento_nomina(request, pedido_id):
    pedido = get_object_or_404(
        Pedido.objects.prefetch_related("items"),
        id=pedido_id,
        usuario=request.user,
        metodo_pago=Pedido.METODO_NOMINA,
    )

    if hasattr(pedido, "solicitud_nomina"):
        return redirect("fondos:detalle_solicitud", solicitud_id=pedido.solicitud_nomina.id)

    if pedido.estado != Pedido.ESTADO_PENDIENTE_SOLICITUD_NOMINA:
        messages.warning(request, "Este pedido no admite una nueva solicitud de nómina.")
        return redirect("pedidos:confirmacion", pedido_id=pedido.id)

    initial = datos_iniciales_solicitud(request.user, pedido)

    if request.method == "POST":
        form = SolicitudDescuentoNominaForm(request.POST)
        if form.is_valid():
            try:
                solicitud = crear_solicitud(pedido, form, request.user)
            except SolicitudError as exc:
                messages.info(request, str(exc))
                return redirect("pedidos:confirmacion", pedido_id=pedido.id)

            if solicitud.esta_pendiente:
                messages.success(
                    request,
                    f"Solicitud #{solicitud.id} enviada al fondo. Quedó pendiente de aprobación.",
                )
            else:
                messages.info(
                    request,
                    f"El fondo respondió tu solicitud #{solicitud.id}: {solicitud.get_estado_display()}.",
                )
            return redirect("fondos:solicitud_exitosa", solicitud_id=solicitud.id)
    else:
        form = SolicitudDescuentoNominaForm(initial=initial)

    return render(
        request,
        "fondos/solicitud_nomina.html",
        {"form": form, "pedido": pedido, "total": pedido.total},
    )


@login_required
def solicitud_exitosa(request, solicitud_id):
    solicitud = get_object_or_404(
        SolicitudDescuentoNomina.objects.select_related("fondo", "pedido"),
        id=solicitud_id,
        usuario=request.user,
    )
    return render(request, "fondos/solicitud_exitosa.html", {"solicitud": solicitud})


@login_required
def mis_solicitudes(request):
    solicitudes = (
        SolicitudDescuentoNomina.objects
        .filter(usuario=request.user)
        .select_related("fondo", "pedido")
        .order_by("-fecha_solicitud")
    )
    return render(request, "fondos/mis_solicitudes.html", {"solicitudes": solicitudes})


@login_required
def detalle_solicitud(request, solicitud_id):
    solicitud = get_object_or_404(
        SolicitudDescuentoNomina.objects
        .select_related("fondo", "pedido")
        .prefetch_related("pedido__items"),
        id=solicitud_id,
        usuario=request.user,
    )
    return render(request, "fondos/detalle_solicitud.html", {"solicitud": solicitud})


# =====================================================
# PORTAL DEL FONDO (GESTORES)
# =====================================================

def _fondos_gestionables(user):
    if user.is_superuser:
        return FondoEmpleado.objects.all()
    return user.fondos_gestionados.all()


def _solicitudes_gestionables(user):
    qs = SolicitudDescuentoNomina.objects.select_related("fondo", "finca", "pedido", "usuario")
    if user.is_superuser:
        return qs
    return qs.filter(fondo__in=user.fondos_gestionados.all())


@login_required
def gestion_solicitudes(request):
    solicitudes = _solicitudes_gestionables(request.user)

    estado = request.GET.get("estado", SolicitudDescuentoNomina.ESTADO_PENDIENTE)
    if estado in dict(SolicitudDescuentoNomina.ESTADOS):
        solicitudes = solicitudes.filter(estado=estado)
    else:
        estado = ""

    busqueda = request.GET.get("q", "").strip()
    if busqueda:
        # El documento está cifrado: se busca por coincidencia exacta usando su huella.
        solicitudes = solicitudes.filter(
            Q(documento_huella=huella(busqueda)) | Q(nombre_completo__icontains=busqueda)
        )

    pagina = Paginator(solicitudes.order_by("fecha_solicitud"), 25).get_page(request.GET.get("page"))
    return render(
        request,
        "fondos/gestion_lista.html",
        {
            "solicitudes": pagina,
            "pagina": pagina,
            "estado": estado,
            "estados": SolicitudDescuentoNomina.ESTADOS,
            "busqueda": busqueda,
            "fondos": _fondos_gestionables(request.user),
        },
    )


@login_required
def gestion_detalle(request, solicitud_id):
    solicitud = get_object_or_404(
        _solicitudes_gestionables(request.user).prefetch_related(
            "pedido__items", "historial__usuario"
        ).select_related("afiliado", "decidido_por"),
        id=solicitud_id,
    )

    form = None
    if solicitud.esta_pendiente:
        form = RespuestaFondoForm(request.POST or None, solicitud=solicitud)
        if request.method == "POST" and form.is_valid():
            datos = form.cleaned_data
            try:
                aplicar_decision(
                    solicitud,
                    estado=datos["estado"],
                    valor_aprobado=datos["valor_aprobado"],
                    vinculado=datos["vinculacion_validada"],
                    cupo_reportado=datos["cupo_disponible_reportado"],
                    referencia=datos["referencia_fondo"],
                    respuesta=datos["respuesta_fondo"],
                    origen=SolicitudDescuentoNomina.ORIGEN_GESTOR,
                    usuario=request.user,
                )
            except DecisionInvalida as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, "Respuesta registrada correctamente.")
                return redirect("fondos:gestion_detalle", solicitud_id=solicitud.id)

    return render(
        request,
        "fondos/gestion_detalle.html",
        {"solicitud": solicitud, "form": form},
    )


@login_required
def gestion_padron(request, fondo_id):
    fondo = get_object_or_404(_fondos_gestionables(request.user), id=fondo_id)
    resultado = None

    form = CargaPadronForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        resultado = importar_padron(
            fondo,
            form.cleaned_data["archivo"].read(),
            desactivar_ausentes=form.cleaned_data["desactivar_ausentes"],
        )
        if resultado.creados or resultado.actualizados:
            messages.success(
                request,
                f"Padrón actualizado: {resultado.creados} nuevos, "
                f"{resultado.actualizados} actualizados, {resultado.desactivados} desactivados.",
            )
        form = CargaPadronForm()

    return render(
        request,
        "fondos/gestion_padron.html",
        {
            "fondo": fondo,
            "form": form,
            "resultado": resultado,
            "total_afiliados": fondo.afiliados.filter(activo=True).count(),
        },
    )


# =====================================================
# REPORTE MENSUAL DE DESCUENTOS POR NÓMINA
# =====================================================

def _periodo_solicitado(request):
    texto = request.GET.get("mes") or request.POST.get("mes")
    return periodo_desde_texto(texto) if texto else periodo_por_defecto()


@login_required
def gestion_reporte(request, fondo_id):
    fondo = get_object_or_404(_fondos_gestionables(request.user), id=fondo_id)
    try:
        periodo = _periodo_solicitado(request)
    except ReporteError as exc:
        messages.error(request, str(exc))
        return redirect("fondos:gestion_reporte", fondo_id=fondo.id)

    formato = request.GET.get("formato")
    if formato:
        try:
            contenido, tipo, nombre = archivo_reporte(fondo, periodo, formato)
        except ReporteError as exc:
            messages.error(request, str(exc))
            return redirect(f"{request.path}?mes={periodo:%Y-%m}")
        respuesta = HttpResponse(contenido, content_type=tipo)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Cache-Control"] = "no-store"
        return respuesta

    corte, solicitudes = solicitudes_del_periodo(fondo, periodo)
    datos = resumen(solicitudes)
    return render(
        request,
        "fondos/gestion_reporte.html",
        {
            "fondo": fondo,
            "periodo": periodo,
            "corte": corte,
            "solicitudes": solicitudes,
            "resumen": datos,
            "cortes": fondo.cortes.all()[:12],
        },
    )


@login_required
@require_POST
def gestion_cerrar_corte(request, fondo_id):
    fondo = get_object_or_404(_fondos_gestionables(request.user), id=fondo_id)
    try:
        periodo = _periodo_solicitado(request)
        corte = cerrar_corte(fondo, periodo, usuario=request.user)
    except ReporteError as exc:
        messages.error(request, str(exc))
    else:
        mensaje = f"Corte {periodo:%Y-%m} cerrado: {corte.cantidad} descuentos por ${corte.total:,.0f}."
        if request.POST.get("enviar"):
            try:
                enviar_corte_por_correo(corte)
                mensaje += " El archivo se envió al fondo por correo."
            except ReporteError as exc:
                messages.warning(request, str(exc))
        messages.success(request, mensaje)
        return redirect(f"{reverse('fondos:gestion_reporte', args=[fondo.id])}?mes={periodo:%Y-%m}")
    return redirect("fondos:gestion_reporte", fondo_id=fondo.id)
