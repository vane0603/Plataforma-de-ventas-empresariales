"""
Registro de entregas. Con descuento por nómina, quien recibe firma en pantalla:
esa firma es el soporte de que el empleado recibió lo que se le descontará.
"""

import base64
import binascii
import io
import logging

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from apps.notificaciones.models import Notificacion
from apps.notificaciones.services import notificar, notificar_al_confirmar

from .models import Entrega, Pedido

logger = logging.getLogger(__name__)

PREFIJO_PNG = "data:image/png;base64,"
TAMANO_MAXIMO_FIRMA = 400 * 1024          # bytes
DIMENSION_MAXIMA_FIRMA = 3000             # píxeles


class EntregaError(Exception):
    pass


def pedidos_por_entregar():
    """Pagados, aprobados por nómina o con "otro medio de pago" (se cobra al entregar), sin entrega."""
    return (
        Pedido.objects
        .filter(
            Q(estado__in=Pedido.ESTADOS_ENTREGABLES)
            | Q(estado=Pedido.ESTADO_PENDIENTE_PAGO, metodo_pago=Pedido.METODO_OTRO)
            | Q(estado=Pedido.ESTADO_PENDIENTE_PAGO, metodo_pago_saldo=Pedido.METODO_OTRO)
        )
        .filter(entrega__isnull=True)
    )


def despachar_pedidos(ids, usuario=None):
    """
    Marca como "En camino" los pedidos por entregar indicados y avisa a cada comprador.
    Ignora los que ya salieron o ya no están por entregar. Devuelve los despachados.
    """
    despachados = []
    with transaction.atomic():
        pedidos = (
            pedidos_por_entregar()
            .filter(pk__in=ids, despachado_en__isnull=True)
            .select_for_update(of=("self",))
            .order_by("pk")
        )
        ahora = timezone.now()
        for pedido in pedidos:
            pedido.despachado_en = ahora
            pedido.despachado_por = usuario
            pedido.save(update_fields=["despachado_en", "despachado_por", "updated_at"])
            notificar_al_confirmar(Notificacion.EVENTO_PEDIDO_DESPACHADO, pedido=pedido)
            despachados.append(pedido)
    return despachados


def decodificar_firma(data_url):
    """
    Convierte el trazo del lienzo (data URL PNG) en bytes PNG validados.
    Devuelve b"" si no hay firma; lanza EntregaError si es inválida o está en blanco.
    """
    data_url = (data_url or "").strip()
    if not data_url:
        return b""
    if not data_url.startswith(PREFIJO_PNG):
        raise EntregaError("La firma no tiene un formato válido.")
    try:
        contenido = base64.b64decode(data_url[len(PREFIJO_PNG):], validate=True)
    except (binascii.Error, ValueError):
        raise EntregaError("La firma no tiene un formato válido.")
    if len(contenido) > TAMANO_MAXIMO_FIRMA:
        raise EntregaError("La firma es demasiado grande.")

    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen.verify()
        imagen = Image.open(io.BytesIO(contenido))
    except (UnidentifiedImageError, OSError):
        raise EntregaError("La firma no es una imagen válida.")
    if imagen.format != "PNG" or max(imagen.size) > DIMENSION_MAXIMA_FIRMA:
        raise EntregaError("La firma no es una imagen válida.")

    # El lienzo es transparente: si no hay ningún píxel visible, la firma está en blanco.
    if imagen.convert("RGBA").getchannel("A").getbbox() is None:
        return b""
    return contenido


def registrar_entrega(pedido, *, recibido_por, firma_png=b"", observaciones="", usuario=None):
    recibido_por = " ".join((recibido_por or "").split())[:150]
    if len(recibido_por) < 3:
        raise EntregaError("Escribe el nombre de quien recibe.")

    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if Entrega.objects.filter(pedido=pedido).exists():
            raise EntregaError("Este pedido ya fue entregado.")
        if not pedido.puede_entregarse:
            raise EntregaError(f"El pedido está en estado «{pedido.get_estado_display()}» y no se puede entregar.")
        if pedido.requiere_firma and not firma_png:
            raise EntregaError("Con descuento por nómina, quien recibe debe firmar.")

        entrega = Entrega(
            pedido=pedido,
            entregado_por=usuario,
            recibido_por=recibido_por,
            observaciones=(observaciones or "").strip(),
        )
        if firma_png:
            entrega.firma.save(f"{pedido.numero}.png", ContentFile(firma_png), save=False)
        entrega.save()

        pedido.estado = Pedido.ESTADO_ENTREGADO
        pedido.save(update_fields=["estado", "updated_at"])
        transaction.on_commit(lambda: notificar_entrega(entrega))
    return entrega


def notificar_entrega(entrega):
    notificar(Notificacion.EVENTO_PEDIDO_ENTREGADO, pedido=entrega.pedido)


def puede_ver_entrega(usuario, pedido):
    """Firma y constancia: repartidores, el dueño del pedido y los gestores de su fondo."""
    if not usuario.is_authenticated:
        return False
    if usuario.has_perm("pedidos.registrar_entrega") or usuario == pedido.usuario:
        return True
    solicitud = getattr(pedido, "solicitud_nomina", None)
    return bool(solicitud and usuario.fondos_gestionados.filter(pk=solicitud.fondo_id).exists())
