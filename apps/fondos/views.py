from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.pedidos.models import Pedido
from .forms import RespuestaFondoForm, SolicitudDescuentoNominaForm
from .models import SolicitudDescuentoNomina
from .services import notificar_fondo_nueva_solicitud, notificar_usuario_respuesta


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

    initial = {
        "nombre_completo": request.user.get_full_name() or request.user.username,
        "correo": request.user.email,
    }

    if request.method == "POST":
        form = SolicitudDescuentoNominaForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
                if SolicitudDescuentoNomina.objects.filter(pedido=pedido).exists():
                    messages.info(request, "Este pedido ya tiene una solicitud de nómina.")
                    return redirect("pedidos:confirmacion", pedido_id=pedido.id)

                solicitud = form.save(commit=False)
                solicitud.usuario = request.user
                solicitud.pedido = pedido
                solicitud.valor_solicitado = pedido.total
                solicitud.estado = SolicitudDescuentoNomina.ESTADO_PENDIENTE
                solicitud.save()

                pedido.estado = Pedido.ESTADO_EN_REVISION_NOMINA
                pedido.save(update_fields=["estado", "updated_at"])

            notificar_fondo_nueva_solicitud(request, solicitud)
            messages.success(
                request,
                f"Solicitud #{solicitud.id} enviada al fondo. Quedó pendiente de aprobación.",
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


def _solicitudes_gestionables(user):
    qs = SolicitudDescuentoNomina.objects.select_related("fondo", "pedido", "usuario")
    if user.is_superuser:
        return qs
    return qs.filter(fondo__gestores=user).distinct()


@login_required
def gestion_solicitudes(request):
    solicitudes = _solicitudes_gestionables(request.user).order_by("estado", "fecha_solicitud")
    return render(request, "fondos/gestion_lista.html", {"solicitudes": solicitudes})


@login_required
def gestion_detalle(request, solicitud_id):
    solicitud = get_object_or_404(
        _solicitudes_gestionables(request.user).prefetch_related("pedido__items"),
        id=solicitud_id,
    )

    estado_anterior = solicitud.estado
    if request.method == "POST":
        form = RespuestaFondoForm(request.POST, instance=solicitud)
        if form.is_valid():
            with transaction.atomic():
                solicitud = form.save()
            if estado_anterior == SolicitudDescuentoNomina.ESTADO_PENDIENTE:
                notificar_usuario_respuesta(solicitud)
            messages.success(request, "Respuesta registrada correctamente.")
            return redirect("fondos:gestion_detalle", solicitud_id=solicitud.id)
    else:
        form = RespuestaFondoForm(instance=solicitud)

    return render(
        request,
        "fondos/gestion_detalle.html",
        {"solicitud": solicitud, "form": form},
    )
