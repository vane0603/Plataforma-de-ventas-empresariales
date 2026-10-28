from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.templatetags.static import static

from ..models import Notificacion
from . import Canal, ErrorEnvio, registrar


@registrar(Notificacion.CANAL_CORREO)
class CanalCorreo(Canal):
    """Correo en HTML con la marca Tío Campo y versión de texto plano."""

    def destino(self, notificacion):
        pedido, solicitud = notificacion.pedido, notificacion.solicitud
        if solicitud is not None:
            return solicitud.correo or (solicitud.usuario.email if solicitud.usuario_id else "")
        return pedido.correo_notificacion if pedido else ""

    def enviar(self, destino, mensaje):
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        contexto = {
            "m": mensaje,
            "politica_url": base + "/politica-de-datos/",
            # PNG (no WebP): algunos clientes de correo no muestran WebP.
            "logo_url": base + static("img/marca/logo-tio-campo.png"),
        }
        correo = EmailMultiAlternatives(
            subject=mensaje.asunto,
            body=render_to_string("notificaciones/correo.txt", contexto),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[destino],
        )
        correo.attach_alternative(render_to_string("notificaciones/correo.html", contexto), "text/html")
        try:
            correo.send()
        except Exception as exc:  # SMTP, red, autenticación...
            raise ErrorEnvio(f"No se pudo enviar el correo: {exc}") from exc
        return ""
