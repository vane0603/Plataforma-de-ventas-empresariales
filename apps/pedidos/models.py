import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.carrito.models import Carrito
from apps.productos.models import ProductoPresentacion
from apps.promociones.models import Combo


class Pedido(models.Model):

    METODO_ELECTRONICO = "ELECTRONICO"
    METODO_OTRO = "OTRO"
    METODO_NOMINA = "NOMINA"

    METODOS_PAGO = [
        (METODO_ELECTRONICO, "Pago electrónico"),
        (METODO_OTRO, "Otro medio de pago"),
        (METODO_NOMINA, "Descuento por nómina"),
    ]

    ESTADO_PENDIENTE_PAGO = "PENDIENTE_PAGO"
    ESTADO_PENDIENTE_SOLICITUD_NOMINA = "PEND_SOL_NOMINA"
    ESTADO_EN_REVISION_NOMINA = "REVISION_NOMINA"
    ESTADO_APROBADO_NOMINA = "APROBADO_NOMINA"
    ESTADO_APROBADO_PARCIAL = "APROBADO_PARCIAL"
    ESTADO_RECHAZADO_NOMINA = "RECHAZADO_NOMINA"
    ESTADO_PAGADO = "PAGADO"
    ESTADO_CANCELADO = "CANCELADO"

    ESTADOS = [
        (ESTADO_PENDIENTE_PAGO, "Pendiente de pago"),
        (
            ESTADO_PENDIENTE_SOLICITUD_NOMINA,
            "Pendiente de solicitud de nómina",
        ),
        (
            ESTADO_EN_REVISION_NOMINA,
            "En revisión por el fondo",
        ),
        (
            ESTADO_APROBADO_NOMINA,
            "Aprobado por nómina",
        ),
        (
            ESTADO_APROBADO_PARCIAL,
            "Aprobado parcialmente",
        ),
        (
            ESTADO_RECHAZADO_NOMINA,
            "Rechazado por el fondo",
        ),
        (
            ESTADO_PAGADO,
            "Pagado",
        ),
        (
            ESTADO_CANCELADO,
            "Cancelado",
        ),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pedidos",
    )

    carrito = models.OneToOneField(
        Carrito,
        on_delete=models.PROTECT,
        related_name="pedido",
        null=True,
        blank=True,
    )

    numero = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )

    metodo_pago = models.CharField(
        max_length=20,
        choices=METODOS_PAGO,
    )

    estado = models.CharField(
        max_length=30,
        choices=ESTADOS,
        default=ESTADO_PENDIENTE_PAGO,
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    direccion_entrega = models.CharField(
        max_length=250,
    )

    ciudad = models.CharField(
        max_length=120,
    )

    observaciones = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Pedido"
        verbose_name_plural = "Pedidos"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):

        if not self.numero:

            fecha = timezone.localtime().strftime(
                "%Y%m%d"
            )

            self.numero = (
                f"PED-{fecha}-"
                f"{uuid.uuid4().hex[:8].upper()}"
            )

        super().save(
            *args,
            **kwargs,
        )

    def __str__(self):

        return self.numero


class PedidoItem(models.Model):

    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name="items",
    )

    producto_presentacion = models.ForeignKey(
        ProductoPresentacion,
        on_delete=models.PROTECT,
        related_name="items_pedido",
        null=True,
        blank=True,
    )

    combo = models.ForeignKey(
        Combo,
        on_delete=models.PROTECT,
        related_name="items_pedido",
        null=True,
        blank=True,
    )

    producto_nombre = models.CharField(
        max_length=200,
    )

    referencia = models.CharField(
        max_length=50,
    )

    presentacion = models.CharField(
        max_length=150,
    )

    cantidad = models.PositiveIntegerField()

    precio_unitario = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    class Meta:

        verbose_name = "Ítem de pedido"
        verbose_name_plural = "Ítems de pedido"

        ordering = ["id"]

        constraints = [

            models.CheckConstraint(
                condition=(
                    Q(
                        producto_presentacion__isnull=False,
                        combo__isnull=True,
                    )
                    |
                    Q(
                        producto_presentacion__isnull=True,
                        combo__isnull=False,
                    )
                ),
                name="pedido_item_un_solo_tipo",
            ),

        ]

    @property
    def es_combo(self):

        return self.combo_id is not None

    def __str__(self):

        return (
            f"{self.pedido.numero} - "
            f"{self.producto_nombre}"
        )