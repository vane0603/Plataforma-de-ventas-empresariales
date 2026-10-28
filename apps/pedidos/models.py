import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.carrito.models import Carrito
from apps.core.campos import TextoCifrado
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
    ESTADO_ENTREGADO = "ENTREGADO"

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
        (
            ESTADO_ENTREGADO,
            "Entregado",
        ),
    ]

    METODOS_PAGO_SALDO = [
        (METODO_ELECTRONICO, "Pago electrónico"),
        (METODO_OTRO, "Otro medio de pago"),
    ]

    # Estados desde los que el comprador puede cancelar.
    ESTADOS_CANCELABLES = (
        ESTADO_PENDIENTE_PAGO,
        ESTADO_PENDIENTE_SOLICITUD_NOMINA,
        ESTADO_APROBADO_PARCIAL,
        ESTADO_RECHAZADO_NOMINA,
    )

    # Pedidos listos para entregar: pagados, cubiertos por nómina, o con
    # "otro medio de pago" (se cobra al entregar).
    ESTADOS_ENTREGABLES = (
        ESTADO_PAGADO,
        ESTADO_APROBADO_NOMINA,
    )

    # Estados en los que el fondo no cubrió todo y hay saldo por definir.
    ESTADOS_CON_SALDO_POR_DEFINIR = (
        ESTADO_APROBADO_PARCIAL,
        ESTADO_RECHAZADO_NOMINA,
    )

    # Vacío cuando compra un invitado (pago en línea u otro medio sin cuenta).
    # El descuento por nómina siempre exige usuario.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pedidos",
        null=True,
        blank=True,
    )

    # Datos de contacto del comprador (obligatorios para invitados).
    nombre_contacto = models.CharField(
        max_length=150,
        blank=True,
    )

    correo_contacto = models.EmailField(
        blank=True,
    )

    # Cifrado en reposo (Ley 1581 de 2012).
    telefono_contacto = TextoCifrado(
        blank=True,
    )

    # Autorización expresa para recibir avisos del pedido por WhatsApp.
    avisos_whatsapp = models.BooleanField(
        default=False,
    )

    # Fecha en que se borraron los datos personales por la política de retención.
    anonimizado_en = models.DateTimeField(
        blank=True,
        null=True,
    )

    # Código secreto para que el invitado consulte su pedido desde el enlace del correo.
    codigo_acceso = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
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

    # Parte del total cubierta por el fondo de empleados (descuento por nómina).
    valor_nomina = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    # Medio con el que se paga el saldo no cubierto por nómina
    # (aprobación parcial o rechazo).
    metodo_pago_saldo = models.CharField(
        max_length=20,
        choices=METODOS_PAGO_SALDO,
        blank=True,
    )

    # Salida a entrega ("En camino"). No cambia el estado: el pago sigue igual.
    despachado_en = models.DateTimeField(
        null=True,
        blank=True,
    )

    despachado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pedidos_despachados",
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
        indexes = [
            models.Index(fields=["usuario", "-created_at"]),
            models.Index(fields=["estado"]),
        ]

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

    @property
    def es_invitado(self):

        return self.usuario_id is None

    @property
    def correo_notificacion(self):

        if self.correo_contacto:
            return self.correo_contacto

        return self.usuario.email if self.usuario_id else ""

    @property
    def nombre_cliente(self):

        if self.nombre_contacto:
            return self.nombre_contacto

        if self.usuario_id:
            return self.usuario.get_full_name() or self.usuario.username

        return "cliente"

    @property
    def saldo_pendiente(self):

        return self.total - (self.valor_nomina or 0)

    @property
    def puede_cancelarse(self):

        # Si ya salió a entrega, se resuelve con el repartidor y no desde la tienda.
        return self.estado in self.ESTADOS_CANCELABLES and self.despachado_en is None

    @property
    def puede_entregarse(self):

        if self.estado in self.ESTADOS_ENTREGABLES:
            return True

        return (
            self.estado == self.ESTADO_PENDIENTE_PAGO
            and self.METODO_OTRO in (self.metodo_pago, self.metodo_pago_saldo)
        )

    @property
    def en_camino(self):

        return self.despachado_en is not None and self.estado != self.ESTADO_ENTREGADO

    @property
    def requiere_firma(self):

        # Con descuento por nómina el empleado firma que recibió (soporte del descuento).
        return self.metodo_pago == self.METODO_NOMINA

    @property
    def requiere_definir_saldo(self):

        return (
            self.estado in self.ESTADOS_CON_SALDO_POR_DEFINIR
            and not self.metodo_pago_saldo
        )


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


def almacen_privado():
    """Archivos que NO se publican en /media/ (firmas): solo se sirven con permiso."""
    return FileSystemStorage(location=settings.ARCHIVOS_PRIVADOS_ROOT)


def ruta_firma(entrega, nombre):
    return f"firmas/{timezone.localtime():%Y/%m}/{entrega.pedido.numero}.png"


class Entrega(models.Model):
    """Constancia de entrega de un pedido. Con nómina incluye la firma de quien recibe."""

    pedido = models.OneToOneField(
        Pedido,
        on_delete=models.CASCADE,
        related_name="entrega",
    )

    entregado_en = models.DateTimeField(
        default=timezone.now,
    )

    entregado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entregas_registradas",
    )

    recibido_por = models.CharField(
        max_length=150,
    )

    firma = models.ImageField(
        upload_to=ruta_firma,
        storage=almacen_privado,
        blank=True,
    )

    observaciones = models.TextField(
        blank=True,
    )

    class Meta:
        verbose_name = "Entrega"
        verbose_name_plural = "Entregas"
        ordering = ["-entregado_en"]
        permissions = [
            ("registrar_entrega", "Puede registrar entregas de pedidos"),
        ]

    def __str__(self):
        return f"Entrega {self.pedido.numero}"
