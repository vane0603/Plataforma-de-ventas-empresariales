"""
Casos de uso de pedidos. Las vistas solo validan la entrada HTTP y delegan aquí,
para que la misma lógica sirva a una API, tareas en segundo plano o al admin.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from apps.carrito.models import Carrito
from apps.promociones.models import Combo

from .models import Pedido, PedidoItem


logger = logging.getLogger(__name__)


class PedidoError(Exception):
    pass


def crear_pedido_desde_carrito(
    *, carrito, usuario, metodo_pago, direccion, ciudad, observaciones="", contacto=None, autoriza_datos=False
):
    """
    `usuario` puede ser None (compra como invitado) salvo con descuento por nómina.
    `contacto` = {"nombre", "correo", "telefono"}; obligatorio para invitados.
    """
    contacto = contacto or {}
    if usuario is not None and not usuario.is_authenticated:
        usuario = None
    if metodo_pago not in dict(Pedido.METODOS_PAGO):
        raise PedidoError("Debes seleccionar un medio de pago válido.")
    if usuario is None and metodo_pago == Pedido.METODO_NOMINA:
        raise PedidoError("Para pagar con descuento por nómina debes iniciar sesión.")
    if usuario is None and not (contacto.get("nombre") and contacto.get("correo")):
        raise PedidoError("Escribe tu nombre y correo para continuar.")
    if usuario is None and not autoriza_datos:
        raise PedidoError("Debes autorizar el tratamiento de tus datos para continuar.")
    # Con nómina la dirección la define la finca elegida en la solicitud.
    if metodo_pago != Pedido.METODO_NOMINA:
        if not direccion:
            raise PedidoError("Debes ingresar la dirección de entrega.")
        if not ciudad:
            raise PedidoError("Debes ingresar la ciudad de entrega.")
    else:
        direccion = direccion or "Por definir: finca elegida en la solicitud de nómina"

    with transaction.atomic():
        carrito = Carrito.objects.select_for_update().get(pk=carrito.pk)
        items = list(
            carrito.items
            .select_for_update()
            .select_related("presentacion__producto", "presentacion__presentacion", "combo")
            .order_by("id")
        )
        if not carrito.activo or not items:
            raise PedidoError("Este carrito ya fue procesado o está vacío.")

        # Precios vigentes y disponibilidad (el precio del carrito puede estar desactualizado).
        for item in items:
            if item.combo_id:
                if not item.combo.activo:
                    raise PedidoError(f"El combo {item.combo.nombre} ya no está disponible.")
                item.precio_unitario = item.combo.precio
            else:
                presentacion = item.presentacion
                if not presentacion.activo or not presentacion.producto.activo:
                    raise PedidoError("Uno de los productos del carrito ya no está disponible.")
                item.precio_unitario = presentacion.precio

        # Descuento atómico de stock: evita sobreventa con compras simultáneas.
        for item in items:
            if item.combo_id:
                actualizados = Combo.objects.filter(
                    pk=item.combo_id, stock__gte=item.cantidad
                ).update(stock=F("stock") - item.cantidad)
                if not actualizados:
                    raise PedidoError(
                        f"El combo {item.combo.nombre} no tiene unidades suficientes."
                    )

        total = sum(item.subtotal for item in items)
        pedido = Pedido.objects.create(
            usuario=usuario,
            carrito=carrito,
            metodo_pago=metodo_pago,
            estado=(
                Pedido.ESTADO_PENDIENTE_SOLICITUD_NOMINA
                if metodo_pago == Pedido.METODO_NOMINA
                else Pedido.ESTADO_PENDIENTE_PAGO
            ),
            subtotal=total,
            total=total,
            direccion_entrega=direccion,
            ciudad=ciudad,
            observaciones=observaciones,
            nombre_contacto=contacto.get("nombre", "")[:150],
            correo_contacto=contacto.get("correo", ""),
            telefono_contacto=contacto.get("telefono", "")[:30],
        )

        PedidoItem.objects.bulk_create([
            PedidoItem(
                pedido=pedido,
                combo=item.combo if item.combo_id else None,
                producto_presentacion=None if item.combo_id else item.presentacion,
                producto_nombre=item.nombre_mostrar,
                referencia=item.codigo_mostrar,
                presentacion=item.detalle_mostrar,
                cantidad=item.cantidad,
                precio_unitario=item.precio_unitario,
                subtotal=item.subtotal,
            )
            for item in items
        ])

        carrito.activo = False
        carrito.save(update_fields=["activo", "updated_at"])

        if usuario is None:
            from apps.cuentas.models import AutorizacionDatos, registrar_autorizacion

            registrar_autorizacion(AutorizacionDatos.ORIGEN_CHECKOUT, pedido=pedido)

        transaction.on_commit(lambda: notificar_pedido_creado(pedido))

    return pedido


def notificar_pedido_creado(pedido):
    """Confirmación por correo con el enlace para consultar el pedido (sirve a invitados)."""
    correo = pedido.correo_notificacion
    if not correo:
        return
    enlace = settings.PUBLIC_BASE_URL.rstrip("/") + reverse(
        "pedidos:seguimiento", args=[pedido.codigo_acceso]
    )
    aviso_entrega = (
        "La fecha de entrega se acuerda con tu fondo de empleados."
        if pedido.metodo_pago == Pedido.METODO_NOMINA
        else "Te contactaremos para coordinar la entrega."
    )
    lineas = "\n".join(
        f"- {item.cantidad} x {item.producto_nombre} ({item.presentacion}): ${item.subtotal:,.0f}"
        for item in pedido.items.all()
    )
    send_mail(
        f"Recibimos tu pedido {pedido.numero}",
        (
            f"Hola {pedido.nombre_cliente},\n\n"
            f"Recibimos tu pedido {pedido.numero}.\n\n{lineas}\n\n"
            f"Total: ${pedido.total:,.0f}\n"
            f"Medio de pago: {pedido.get_metodo_pago_display()}\n\n"
            f"{aviso_entrega}\n\n"
            f"Consulta tu pedido aquí: {enlace}\n\n"
            "Gracias por comprar en Tío Campo."
        ),
        settings.DEFAULT_FROM_EMAIL,
        [correo],
        fail_silently=True,
    )


def cancelar_pedido(pedido, usuario=None):
    """Cancela, devuelve stock de combos y libera el cupo de nómina reservado."""
    from apps.fondos.services import liberar_cupo

    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if not pedido.puede_cancelarse:
            raise PedidoError("Este pedido ya no puede cancelarse.")

        for item in pedido.items.filter(combo__isnull=False):
            Combo.objects.filter(pk=item.combo_id).update(stock=F("stock") + item.cantidad)

        solicitud = getattr(pedido, "solicitud_nomina", None)
        if solicitud is not None:
            liberar_cupo(solicitud, usuario=usuario)

        pedido.estado = Pedido.ESTADO_CANCELADO
        pedido.valor_nomina = 0
        pedido.save(update_fields=["estado", "valor_nomina", "updated_at"])
    return pedido


def definir_pago_saldo(pedido, metodo):
    """
    Tras una aprobación parcial (o un rechazo) el comprador decide pagar la
    diferencia con otro medio. El pedido vuelve a 'pendiente de pago' por el saldo.
    """
    if metodo not in dict(Pedido.METODOS_PAGO_SALDO):
        raise PedidoError("Selecciona un medio de pago válido para el saldo.")

    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if not pedido.requiere_definir_saldo:
            raise PedidoError("Este pedido no tiene un saldo por definir.")
        pedido.metodo_pago_saldo = metodo
        pedido.estado = Pedido.ESTADO_PENDIENTE_PAGO
        pedido.updated_at = timezone.now()
        pedido.save(update_fields=["metodo_pago_saldo", "estado", "updated_at"])
    return pedido
