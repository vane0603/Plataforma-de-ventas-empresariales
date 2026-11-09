"""
Casos de uso de pedidos. Las vistas solo validan la entrada HTTP y delegan aquí,
para que la misma lógica sirva a una API, tareas en segundo plano o al admin.
"""

import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.carrito.models import Carrito
from apps.notificaciones.models import Notificacion
from apps.notificaciones.services import notificar
from apps.promociones.models import Combo

from .models import Pedido, PedidoItem


logger = logging.getLogger(__name__)


class PedidoError(Exception):
    pass


def crear_pedido_desde_carrito(
    *, carrito, usuario, metodo_pago, direccion, ciudad, observaciones="", contacto=None, autoriza_datos=False,
    avisos_whatsapp=False, punto_recogida=None,
):
    """
    `usuario` puede ser None (compra como invitado) salvo con descuento por nómina.
    `contacto` = {"nombre", "correo", "telefono"}; obligatorio para invitados.
    Con `punto_recogida` el cliente recoge en tienda y no se pide dirección.
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
    if punto_recogida is not None:
        if metodo_pago == Pedido.METODO_NOMINA:
            raise PedidoError("Con descuento por nómina el pedido se entrega en la finca; no se puede recoger en tienda.")
        if not punto_recogida.activo:
            raise PedidoError("El punto de recogida elegido ya no está disponible.")
        direccion, ciudad = f"{punto_recogida.nombre} - {punto_recogida.direccion}"[:250], punto_recogida.ciudad
    elif metodo_pago != Pedido.METODO_NOMINA:
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
            tipo_entrega=Pedido.TIPO_TIENDA if punto_recogida is not None else Pedido.TIPO_DOMICILIO,
            punto_recogida=punto_recogida,
            observaciones=observaciones,
            nombre_contacto=contacto.get("nombre", "")[:150],
            correo_contacto=contacto.get("correo", ""),
            telefono_contacto=contacto.get("telefono", "")[:30],
            avisos_whatsapp=bool(avisos_whatsapp),
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
    """Confirmación con el enlace para consultar el pedido (sirve a invitados)."""
    notificar(Notificacion.EVENTO_PEDIDO_CREADO, pedido=pedido)


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
