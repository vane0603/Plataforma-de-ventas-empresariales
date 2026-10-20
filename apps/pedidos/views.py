from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.carrito.views import obtener_carrito
from apps.pagos.services import pedido_pagable_en_linea

from .acceso import pedido_accesible, recordar_pedido
from .forms import CheckoutForm
from .models import Pedido
from .services import PedidoError, cancelar_pedido, crear_pedido_desde_carrito, definir_pago_saldo

# Datos que el invitado ya escribió, para no perderlos si debe iniciar sesión (nómina).
SESSION_BORRADOR = "checkout_borrador"
CAMPOS_BORRADOR = ("nombre", "correo", "telefono", "direccion_entrega", "ciudad", "observaciones", "metodo_pago")


def checkout(request):
    """
    Cualquiera puede finalizar la compra. Solo el descuento por nómina pide
    iniciar sesión, porque el fondo debe verificar al titular de la cuenta.
    """
    carrito = obtener_carrito(request)
    items = (
        carrito.items
        .select_related(
            "presentacion",
            "presentacion__producto",
            "presentacion__presentacion",
            "combo",
        )
        .order_by("id")
    )

    if not items.exists():
        messages.warning(request, "Tu carrito está vacío.")
        return redirect("carrito:detalle")

    if request.method == "POST":
        form = CheckoutForm(request.POST, usuario=request.user)
        if form.is_valid():
            if form.requiere_login:
                request.session[SESSION_BORRADOR] = {c: request.POST.get(c, "") for c in CAMPOS_BORRADOR}
                messages.info(
                    request,
                    "Para pagar con descuento por nómina inicia sesión o crea tu cuenta. "
                    "Tu carrito y tus datos se conservan.",
                )
                destino = reverse("pedidos:checkout")
                return redirect(f"{reverse('login')}?{urlencode({'next': destino})}")

            try:
                pedido = crear_pedido_desde_carrito(
                    carrito=carrito,
                    usuario=request.user if request.user.is_authenticated else None,
                    metodo_pago=form.cleaned_data["metodo_pago"],
                    direccion=form.cleaned_data["direccion_entrega"].strip(),
                    ciudad=form.cleaned_data["ciudad"].strip(),
                    observaciones=form.cleaned_data["observaciones"].strip(),
                    contacto=form.datos_contacto(),
                    autoriza_datos=form.cleaned_data["autoriza_tratamiento"],
                )
            except PedidoError as exc:
                messages.error(request, str(exc))
                return redirect("pedidos:checkout")

            request.session.pop(SESSION_BORRADOR, None)
            if pedido.es_invitado:
                recordar_pedido(request, pedido)

            if pedido.metodo_pago == Pedido.METODO_NOMINA:
                return redirect("fondos:solicitar_descuento_nomina", pedido_id=pedido.id)

            messages.success(request, f"Pedido {pedido.numero} creado correctamente.")
            return redirect("pedidos:confirmacion", pedido_id=pedido.id)
    else:
        inicial = request.session.get(SESSION_BORRADOR, {}).copy()
        if request.user.is_authenticated:
            inicial.setdefault("nombre", request.user.get_full_name())
            inicial.setdefault("correo", request.user.email)
        form = CheckoutForm(initial=inicial or None, usuario=request.user)

    return render(
        request,
        "pedidos/checkout.html",
        {
            "form": form,
            "carrito": carrito,
            "items": items,
            "total": carrito.total,
            "metodos": Pedido.METODOS_PAGO,
        },
    )


def confirmacion(request, pedido_id):
    pedido = pedido_accesible(
        request,
        pedido_id,
        Pedido.objects.prefetch_related("items").select_related("solicitud_nomina"),
    )
    return render(
        request,
        "pedidos/confirmacion.html",
        {
            "pedido": pedido,
            "metodos_saldo": Pedido.METODOS_PAGO_SALDO,
            "puede_pagar_en_linea": pedido_pagable_en_linea(pedido),
            "transacciones": pedido.transacciones.all()[:5],
        },
    )


def seguimiento(request, codigo):
    """Enlace del correo: el invitado entra a su pedido sin cuenta."""
    pedido = get_object_or_404(Pedido, codigo_acceso=codigo)
    if pedido.es_invitado:
        recordar_pedido(request, pedido)
    elif request.user != pedido.usuario:
        messages.info(request, "Inicia sesión para ver este pedido.")
        destino = reverse("pedidos:confirmacion", args=[pedido.id])
        return redirect(f"{reverse('login')}?{urlencode({'next': destino})}")
    return redirect("pedidos:confirmacion", pedido_id=pedido.id)


@require_POST
def pagar_saldo(request, pedido_id):
    pedido = pedido_accesible(request, pedido_id)
    try:
        pedido = definir_pago_saldo(pedido, request.POST.get("metodo_pago_saldo", ""))
    except PedidoError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Listo. El saldo de ${pedido.saldo_pendiente:,.0f} quedó pendiente de pago "
            f"por {pedido.get_metodo_pago_saldo_display().lower()}.",
        )
    return redirect("pedidos:confirmacion", pedido_id=pedido.id)


@require_POST
def cancelar(request, pedido_id):
    pedido = pedido_accesible(request, pedido_id)
    try:
        cancelar_pedido(pedido, usuario=request.user if request.user.is_authenticated else None)
    except PedidoError as exc:
        messages.error(request, str(exc))
    else:
        messages.info(request, f"El pedido {pedido.numero} fue cancelado.")
    return redirect("pedidos:confirmacion", pedido_id=pedido.id)


@login_required
def mis_pedidos(request):
    pedidos = (
        Pedido.objects
        .filter(usuario=request.user)
        .order_by("-created_at")
    )
    return render(request, "pedidos/mis_pedidos.html", {"pedidos": pedidos})
