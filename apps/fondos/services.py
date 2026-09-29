from django.conf import settings
from django.db import models
from django.utils import timezone


class FondoEmpleado(models.Model):
    nombre = models.CharField(max_length=200, unique=True)
    nit = models.CharField(max_length=50, blank=True)
    correo = models.EmailField(blank=True)
    telefono = models.CharField(max_length=50, blank=True)
    responsable = models.CharField(max_length=200, blank=True)
    gestores = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="fondos_gestionados",
        blank=True,
        help_text="Usuarios autorizados para revisar solicitudes de este fondo.",
    )
    activo = models.BooleanField(default=True)
    observaciones = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fondo de empleados"
        verbose_name_plural = "Fondos de empleados"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class SolicitudDescuentoNomina(models.Model):
    ESTADO_PENDIENTE = "PENDIENTE"
    ESTADO_APROBADA = "APROBADA"
    ESTADO_APROBADA_PARCIAL = "APROBADA_PARCIAL"
    ESTADO_RECHAZADA = "RECHAZADA"

    ESTADOS = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_APROBADA, "Aprobada"),
        (ESTADO_APROBADA_PARCIAL, "Aprobada parcialmente"),
        (ESTADO_RECHAZADA, "Rechazada"),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="solicitudes_nomina",
    )
    fondo = models.ForeignKey(
        FondoEmpleado,
        on_delete=models.PROTECT,
        related_name="solicitudes",
    )
    pedido = models.OneToOneField(
        "pedidos.Pedido",
        on_delete=models.PROTECT,
        related_name="solicitud_nomina",
        null=True,
        blank=True,
    )

    nombre_completo = models.CharField(max_length=200)
    documento = models.CharField(max_length=50)
    telefono = models.CharField(max_length=50, blank=True)
    correo = models.EmailField(blank=True)
    empresa = models.CharField(max_length=200, default="Tío Campo")
    numero_afiliado = models.CharField(max_length=100, blank=True)

    valor_solicitado = models.DecimalField(max_digits=12, decimal_places=2)
    vinculacion_validada = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="¿Trabaja/está afiliado con la entidad?",
    )
    valor_aprobado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )
    cupo_disponible_reportado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
    )
    respuesta_fondo = models.TextField(blank=True)
    observaciones_usuario = models.TextField(blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default=ESTADO_PENDIENTE)
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_respuesta = models.DateTimeField(blank=True, null=True)
    referencia_fondo = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "Solicitud de descuento por nómina"
        verbose_name_plural = "Solicitudes de descuento por nómina"
        ordering = ["-fecha_solicitud"]

    def __str__(self):
        return f"Solicitud #{self.id} - {self.nombre_completo}"

    def sincronizar_estado_pedido(self):
        if not self.pedido_id:
            return

        from apps.pedidos.models import Pedido

        mapa = {
            self.ESTADO_PENDIENTE: Pedido.ESTADO_EN_REVISION_NOMINA,
            self.ESTADO_APROBADA: Pedido.ESTADO_APROBADO_NOMINA,
            self.ESTADO_APROBADA_PARCIAL: Pedido.ESTADO_APROBADO_PARCIAL,
            self.ESTADO_RECHAZADA: Pedido.ESTADO_RECHAZADO_NOMINA,
        }
        estado_pedido = mapa.get(self.estado)
        if estado_pedido and self.pedido.estado != estado_pedido:
            Pedido.objects.filter(pk=self.pedido_id).update(estado=estado_pedido)
            self.pedido.estado = estado_pedido

    def save(self, *args, **kwargs):
        if self.estado != self.ESTADO_PENDIENTE and not self.fecha_respuesta:
            self.fecha_respuesta = timezone.now()
        elif self.estado == self.ESTADO_PENDIENTE:
            self.fecha_respuesta = None

        super().save(*args, **kwargs)
        self.sincronizar_estado_pedido()
