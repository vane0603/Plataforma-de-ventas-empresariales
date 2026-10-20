from django.conf import settings
from django.db import models


class AutorizacionDatos(models.Model):
    """
    Prueba de la autorización de tratamiento de datos (Ley 1581 de 2012, art. 9;
    Decreto 1377 de 2013, art. 8): quién autorizó, cuándo, dónde y qué versión
    de la política aceptó. Las solicitudes de nómina guardan la suya en su propio modelo.
    """

    ORIGEN_REGISTRO = "REGISTRO"
    ORIGEN_CHECKOUT = "CHECKOUT"

    ORIGENES = [
        (ORIGEN_REGISTRO, "Creación de cuenta"),
        (ORIGEN_CHECKOUT, "Compra como invitado"),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="autorizaciones_datos",
        null=True,
        blank=True,
    )
    pedido = models.ForeignKey(
        "pedidos.Pedido",
        on_delete=models.CASCADE,
        related_name="autorizaciones_datos",
        null=True,
        blank=True,
    )
    origen = models.CharField(max_length=10, choices=ORIGENES)
    version_politica = models.CharField(max_length=20)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Autorización de datos"
        verbose_name_plural = "Autorizaciones de datos"
        ordering = ["-fecha"]

    def __str__(self):
        titular = self.usuario or (self.pedido and self.pedido.numero) or "—"
        return f"{self.get_origen_display()} · {titular} · v{self.version_politica}"


def registrar_autorizacion(origen, usuario=None, pedido=None):
    return AutorizacionDatos.objects.create(
        usuario=usuario,
        pedido=pedido,
        origen=origen,
        version_politica=settings.POLITICA_DATOS_VERSION,
    )
