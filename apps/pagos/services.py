"""
Casos de uso de pagos en línea. `aplicar_evento` es el único lugar que cambia
el estado de una transacción y marca el pedido como pagado.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.urls import reverse

from apps.notificaciones.models import Notificacion
from apps.notificaciones.services import notificar
from apps.pedidos.models import Pedido

from .models import TransaccionPago
from .pasarelas import obtener_pasarela

logger = logging.getLogger(__name__)


class PagoError(Exception):
    pass


def pedido_pagable_en_linea(pedido):
    return (
        pedido.estado == Pedido.ESTADO_PENDIENTE_PAGO
        and pedido.saldo_pendiente > 0
        and Pedido.METODO_ELECTRONICO in (pedido.metodo_pago, pedido.metodo_pago_saldo)
    )


def iniciar_pago(pedido, correo=""):
    """Crea un intento de pago por el saldo del pedido y devuelve (transaccion, url_checkout)."""
    pasarela = obtener_pasarela()

    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if not pedido_pagable_en_linea(pedido):
            raise PagoError("Este pedido no tiene pagos en línea pendientes.")

        intento = pedido.transacciones.count() + 1
        transaccion = TransaccionPago.objects.create(
            pedido=pedido,
            referencia=f"{pedido.numero}-{intento}",
            proveedor=pasarela.codigo,
            monto_centavos=int(round(pedido.saldo_pendiente * 100)),
            moneda="COP",
        )

    url_retorno = settings.PUBLIC_BASE_URL.rstrip("/") + reverse("pagos:retorno")
    return transaccion, pasarela.url_checkout(transaccion, url_retorno, correo)


def aplicar_evento(evento):
    """
    Aplica el resultado informado por la pasarela (webhook o consulta).
    Es idempotente: la pasarela puede reenviar el mismo evento varias veces.
    """
    with transaction.atomic():
        transaccion = (
            TransaccionPago.objects
            .select_for_update()
            .filter(referencia=evento.referencia)
            .first()
        )
        if transaccion is None:
            logger.warning("Evento de pago con referencia desconocida: %s", evento.referencia)
            return None

        anterior = transaccion.estado
        es_anulacion = (
            anterior == TransaccionPago.ESTADO_APROBADA
            and evento.estado == TransaccionPago.ESTADO_ANULADA
        )
        if anterior in TransaccionPago.ESTADOS_FINALES and not es_anulacion:
            return transaccion
        if evento.estado == anterior and evento.id_externo == transaccion.id_externo:
            return transaccion

        transaccion.id_externo = evento.id_externo
        transaccion.metodo = evento.metodo
        transaccion.respuesta = evento.datos

        if evento.monto_centavos != transaccion.monto_centavos:
            logger.error(
                "Monto distinto en %s: esperado %s, recibido %s",
                transaccion.referencia, transaccion.monto_centavos, evento.monto_centavos,
            )
            transaccion.estado = TransaccionPago.ESTADO_ERROR
            transaccion.save()
            return transaccion

        transaccion.estado = evento.estado
        transaccion.save()

        pedido = Pedido.objects.select_for_update().get(pk=transaccion.pedido_id)
        if evento.estado == TransaccionPago.ESTADO_APROBADA:
            if pedido.estado == Pedido.ESTADO_PAGADO:
                logger.error("Pedido %s ya estaba pagado: revisar doble cobro (%s).", pedido, transaccion)
            else:
                pedido.estado = Pedido.ESTADO_PAGADO
                pedido.save(update_fields=["estado", "updated_at"])
                transaction.on_commit(lambda: notificar_pago_aprobado(transaccion))
        elif es_anulacion and pedido.estado == Pedido.ESTADO_PAGADO:
            pedido.estado = Pedido.ESTADO_PENDIENTE_PAGO
            pedido.save(update_fields=["estado", "updated_at"])

    return transaccion


def notificar_pago_aprobado(transaccion):
    notificar(
        Notificacion.EVENTO_PAGO_APROBADO,
        pedido=transaccion.pedido,
        extra={"monto": str(transaccion.monto), "referencia": transaccion.referencia},
    )
