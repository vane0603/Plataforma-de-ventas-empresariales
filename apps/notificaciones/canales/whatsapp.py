"""
WhatsApp Cloud API (oficial de Meta). Se activa al definir WHATSAPP_TOKEN y
WHATSAPP_PHONE_NUMBER_ID en el .env. Los avisos que inicia la empresa solo se
pueden enviar con plantillas aprobadas por Meta (ver PLANTILLAS_WHATSAPP).
"""

import json
import logging
import re
import urllib.error
import urllib.request

from django.conf import settings

from ..models import Notificacion
from . import Canal, ErrorEnvio, registrar

logger = logging.getLogger(__name__)

URL_API = "https://graph.facebook.com/{version}/{telefono_id}/messages"


def normalizar_celular(numero, indicativo=None):
    """Formato internacional sin '+': '300 123 4567' -> '573001234567'. Vacío si no es válido."""
    indicativo = indicativo or settings.WHATSAPP_INDICATIVO_PAIS
    digitos = re.sub(r"\D", "", numero or "")
    if (numero or "").strip().startswith("+") or digitos.startswith("00"):
        digitos = digitos.lstrip("0")
    elif len(digitos) == 10 and digitos.startswith("3"):
        # Celular colombiano sin indicativo.
        digitos = indicativo + digitos
    return digitos if 11 <= len(digitos) <= 15 else ""


@registrar(Notificacion.CANAL_WHATSAPP)
class CanalWhatsApp(Canal):

    @classmethod
    def habilitado(cls):
        return bool(settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID)

    def destino(self, notificacion):
        pedido, solicitud = notificacion.pedido, notificacion.solicitud
        if pedido is None and solicitud is not None and solicitud.pedido_id:
            pedido = solicitud.pedido
        if solicitud is None and pedido is not None:
            solicitud = getattr(pedido, "solicitud_nomina", None)
        # Solo con autorización expresa del comprador (Ley 1581 y política de Meta).
        if pedido is None or not pedido.avisos_whatsapp:
            return ""
        telefono = pedido.telefono_contacto or (solicitud.telefono if solicitud is not None else "")
        return normalizar_celular(telefono)

    def enviar(self, destino, mensaje):
        cuerpo = {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "template",
            "template": {
                "name": mensaje.plantilla,
                "language": {"code": settings.WHATSAPP_IDIOMA},
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)[:1000]} for p in mensaje.parametros],
                }],
            },
        }
        peticion = urllib.request.Request(
            URL_API.format(version=settings.WHATSAPP_API_VERSION, telefono_id=settings.WHATSAPP_PHONE_NUMBER_ID),
            data=json.dumps(cuerpo).encode(),
            headers={
                "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(peticion, timeout=settings.NOTIFICACIONES_TIMEOUT) as respuesta:
                datos = json.loads(respuesta.read().decode())
        except urllib.error.HTTPError as exc:
            raise ErrorEnvio(f"WhatsApp respondió {exc.code}: {_detalle_error(exc)}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise ErrorEnvio(f"No se pudo contactar a WhatsApp: {exc}") from exc

        mensajes = datos.get("messages") or [{}]
        return mensajes[0].get("id", "")


def _detalle_error(exc):
    try:
        error = json.loads(exc.read().decode()).get("error", {})
        return error.get("message") or str(error)
    except (ValueError, AttributeError):
        return exc.reason
