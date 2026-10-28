"""
Punto único para avisar al comprador. Cada aviso queda registrado (admin →
Notificaciones); un fallo de envío nunca interrumpe la compra ni la entrega:
queda como "Fallida" y se reintenta con `python manage.py reenviar_notificaciones`.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .canales import ErrorEnvio, canales_activos, obtener_canal
from .mensajes import construir_mensaje
from .models import Notificacion

logger = logging.getLogger(__name__)

MAXIMO_INTENTOS = 5


def notificar(evento, *, pedido=None, solicitud=None, extra=None):
    """Envía el aviso por cada canal activo. Llamar después del commit (ver `notificar_al_confirmar`)."""
    enviadas = []
    for canal in canales_activos():
        base = Notificacion(evento=evento, canal=canal.codigo, pedido=pedido, solicitud=solicitud, extra=extra or {})
        destino = canal.destino(base)
        if not destino:
            continue
        # Un mismo evento no se repite por canal (p. ej. si el webhook de pago llega dos veces).
        repetida = Notificacion.objects.filter(
            evento=evento, canal=canal.codigo, pedido=pedido, solicitud=solicitud,
            estado=Notificacion.ESTADO_ENVIADA,
        ).exists()
        if repetida:
            continue
        base.destino = destino
        base.save()
        enviadas.append(enviar(base, canal))
    return enviadas


def notificar_al_confirmar(evento, **datos):
    """Programa el aviso para cuando la transacción se confirme (si se revierte, no se envía)."""
    transaction.on_commit(lambda: notificar(evento, **datos))


def enviar(notificacion, canal=None):
    canal = canal or obtener_canal(notificacion.canal)
    notificacion.intentos += 1
    try:
        mensaje = construir_mensaje(notificacion)
        notificacion.id_externo = canal.enviar(notificacion.destino, mensaje) or ""
    except ErrorEnvio as exc:
        _marcar_fallida(notificacion, str(exc))
    except Exception as exc:  # Nunca romper el flujo del pedido por un aviso.
        logger.exception("Error inesperado enviando la notificación %s", notificacion.pk)
        _marcar_fallida(notificacion, f"Error inesperado: {exc}")
    else:
        notificacion.estado = Notificacion.ESTADO_ENVIADA
        notificacion.enviada_en = timezone.now()
        notificacion.error = ""
    notificacion.save()
    return notificacion


def _marcar_fallida(notificacion, error):
    logger.warning("Notificación %s (%s) fallida: %s", notificacion.pk, notificacion.canal, error)
    notificacion.estado = Notificacion.ESTADO_FALLIDA
    notificacion.error = error[:500]


def reenviar_fallidas(horas=72, maximo_intentos=MAXIMO_INTENTOS):
    """Reintenta las fallidas recientes cuyo canal siga activo. Devuelve (enviadas, fallidas)."""
    activos = {canal.codigo for canal in canales_activos()}
    pendientes = Notificacion.objects.filter(
        estado=Notificacion.ESTADO_FALLIDA,
        intentos__lt=maximo_intentos,
        created_at__gte=timezone.now() - timedelta(hours=horas),
        canal__in=activos,
    ).select_related("pedido", "solicitud")

    enviadas = fallidas = 0
    for notificacion in pendientes:
        if enviar(notificacion).estado == Notificacion.ESTADO_ENVIADA:
            enviadas += 1
        else:
            fallidas += 1
    return enviadas, fallidas
