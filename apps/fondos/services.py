from django.conf import settings
from django.core.mail import send_mail


def notificar_fondo_nueva_solicitud(solicitud):
    """
    Notifica a los gestores del fondo que existe
    una nueva solicitud de descuento por nómina.
    """

    gestores = solicitud.fondo.gestores.filter(
        is_active=True
    ).exclude(
        email=""
    )

    destinatarios = list(
        gestores.values_list("email", flat=True)
    )

    if not destinatarios:
        return

    asunto = f"Nueva solicitud de descuento por nómina #{solicitud.id}"

    mensaje = (
        f"Se ha recibido una nueva solicitud de descuento por nómina.\n\n"
        f"Solicitante: {solicitud.nombre_completo}\n"
        f"Documento: {solicitud.documento}\n"
        f"Empresa: {solicitud.empresa}\n"
        f"Teléfono: {solicitud.telefono}\n"
        f"Correo: {solicitud.correo}\n"
        f"Valor solicitado: ${solicitud.valor_solicitado:,.2f}\n"
        f"Fondo: {solicitud.fondo.nombre}\n"
    )

    if solicitud.numero_afiliado:
        mensaje += (
            f"Número de afiliado: "
            f"{solicitud.numero_afiliado}\n"
        )

    if solicitud.observaciones_usuario:
        mensaje += (
            f"\nObservaciones del usuario:\n"
            f"{solicitud.observaciones_usuario}\n"
        )

    mensaje += (
        "\nPor favor, ingrese al sistema para revisar "
        "y gestionar esta solicitud.\n"
    )

    send_mail(
        asunto,
        mensaje,
        settings.DEFAULT_FROM_EMAIL,
        destinatarios,
        fail_silently=True,
    )


def notificar_usuario_respuesta(solicitud):
    """
    Envía una notificación al usuario cuando se responde
    una solicitud de descuento por nómina.
    """

    if not solicitud.correo:
        return

    asunto = f"Respuesta a solicitud #{solicitud.id}"

    mensaje = (
        f"Hola {solicitud.nombre_completo},\n\n"
        f"Su solicitud de descuento por nómina ha sido actualizada.\n\n"
        f"Estado: {solicitud.get_estado_display()}\n"
    )

    if solicitud.respuesta_fondo:
        mensaje += (
            f"\nRespuesta del fondo:\n"
            f"{solicitud.respuesta_fondo}\n"
        )

    if solicitud.valor_aprobado is not None:
        mensaje += (
            f"\nValor aprobado: "
            f"${solicitud.valor_aprobado:,.2f}\n"
        )

    if solicitud.cupo_disponible_reportado is not None:
        mensaje += (
            f"Cupo disponible reportado: "
            f"${solicitud.cupo_disponible_reportado:,.2f}\n"
        )

    mensaje += (
        "\nSi tiene alguna inquietud, comuníquese con "
        "el área correspondiente.\n\n"
        "Cordialmente,\n"
        "Equipo de atención"
    )

    send_mail(
        asunto,
        mensaje,
        settings.DEFAULT_FROM_EMAIL,
        [solicitud.correo],
        fail_silently=True,
    )