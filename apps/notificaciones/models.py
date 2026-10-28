from django.db import models

from apps.core.campos import TextoCifrado


class Notificacion(models.Model):
    """
    Registro de cada aviso enviado al comprador (auditoría y reintentos).
    No guarda el contenido del mensaje: se arma de nuevo desde el pedido al reintentar.
    """

    EVENTO_PEDIDO_CREADO = "PEDIDO_CREADO"
    EVENTO_NOMINA_APROBADA = "NOMINA_APROBADA"
    EVENTO_NOMINA_PARCIAL = "NOMINA_PARCIAL"
    EVENTO_NOMINA_RECHAZADA = "NOMINA_RECHAZADA"
    EVENTO_PAGO_APROBADO = "PAGO_APROBADO"
    EVENTO_PEDIDO_DESPACHADO = "PEDIDO_DESPACHADO"
    EVENTO_PEDIDO_ENTREGADO = "PEDIDO_ENTREGADO"

    EVENTOS = [
        (EVENTO_PEDIDO_CREADO, "Pedido recibido"),
        (EVENTO_NOMINA_APROBADA, "Nómina aprobada"),
        (EVENTO_NOMINA_PARCIAL, "Nómina aprobada parcialmente"),
        (EVENTO_NOMINA_RECHAZADA, "Nómina rechazada"),
        (EVENTO_PAGO_APROBADO, "Pago aprobado"),
        (EVENTO_PEDIDO_DESPACHADO, "Pedido en camino"),
        (EVENTO_PEDIDO_ENTREGADO, "Pedido entregado"),
    ]

    CANAL_CORREO = "CORREO"
    CANAL_WHATSAPP = "WHATSAPP"

    CANALES = [
        (CANAL_CORREO, "Correo"),
        (CANAL_WHATSAPP, "WhatsApp"),
    ]

    ESTADO_PENDIENTE = "PENDIENTE"
    ESTADO_ENVIADA = "ENVIADA"
    ESTADO_FALLIDA = "FALLIDA"

    ESTADOS = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_ENVIADA, "Enviada"),
        (ESTADO_FALLIDA, "Fallida"),
    ]

    evento = models.CharField(max_length=30, choices=EVENTOS)
    canal = models.CharField(max_length=10, choices=CANALES)
    estado = models.CharField(max_length=10, choices=ESTADOS, default=ESTADO_PENDIENTE)

    pedido = models.ForeignKey(
        "pedidos.Pedido",
        on_delete=models.CASCADE,
        related_name="notificaciones",
        null=True,
        blank=True,
    )
    solicitud = models.ForeignKey(
        "fondos.SolicitudDescuentoNomina",
        on_delete=models.CASCADE,
        related_name="notificaciones",
        null=True,
        blank=True,
    )

    # Correo o celular de destino. Cifrado en reposo (Ley 1581 de 2012).
    destino = TextoCifrado(blank=True)
    # Datos del evento que no están en el pedido (p. ej. referencia del pago).
    extra = models.JSONField(default=dict, blank=True)

    intentos = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True)
    id_externo = models.CharField(
        max_length=120,
        blank=True,
        help_text="Identificador del mensaje en el proveedor (p. ej. WhatsApp).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    enviada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Notificación"
        verbose_name_plural = "Notificaciones"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["estado", "created_at"]),
            models.Index(fields=["evento", "canal"]),
        ]

    def __str__(self):
        return f"{self.get_evento_display()} · {self.get_canal_display()}"
