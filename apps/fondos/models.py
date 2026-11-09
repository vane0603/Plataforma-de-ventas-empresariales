from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

from apps.core.campos import TextoCifrado
from apps.core.cifrado import enmascarar, huella, normalizar_documento


class FondoEmpleado(models.Model):
    """
    Entidad (fondo de empleados / empresa) que respalda el descuento por nómina.

    `modo_verificacion` define CÓMO se valida que el comprador es empleado/afiliado:
    - MANUAL: un gestor del fondo revisa cada solicitud en el portal.
    - PADRON: se consulta el padrón de afiliados cargado por el fondo (CSV).
    - API: se consulta en línea un servicio web expuesto por el fondo.

    Si `decision_automatica` está activo y la verificación es concluyente,
    la plataforma aprueba total/parcialmente o rechaza sin intervención humana.
    """

    MODO_MANUAL = "MANUAL"
    MODO_PADRON = "PADRON"
    MODO_API = "API"

    MODOS_VERIFICACION = [
        (MODO_MANUAL, "Revisión manual del gestor"),
        (MODO_PADRON, "Padrón de afiliados cargado"),
        (MODO_API, "Servicio web del fondo"),
    ]

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
    modo_verificacion = models.CharField(
        max_length=10,
        choices=MODOS_VERIFICACION,
        default=MODO_MANUAL,
    )
    decision_automatica = models.BooleanField(
        default=False,
        help_text=(
            "Si la verificación es concluyente, aprobar/rechazar automáticamente. "
            "Si no lo es (o falla el servicio), la solicitud queda para revisión manual."
        ),
    )
    api_url = models.URLField(
        blank=True,
        help_text="Solo modo API: endpoint del fondo que responde la verificación.",
    )
    api_token_env = models.CharField(
        max_length=100,
        blank=True,
        help_text=(
            "Solo modo API: NOMBRE de la variable de entorno que contiene el token. "
            "El token nunca se guarda en la base de datos."
        ),
    )
    descuento_empleados = models.DecimalField(
        "descuento para empleados (%)",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text=(
            "Porcentaje que se descuenta de los productos (no de los combos) cuando un empleado compra "
            "por nómina con este fondo. 0 = sin descuento. Si el fondo rechaza la solicitud, el descuento se quita."
        ),
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


class ConfiguracionSiigo(models.Model):
    """
    Datos para exportar los pedidos de un fondo como facturas al "modelo de importación de
    movimiento contable" de Siigo. Solo los fondos con esta configuración activa se exportan.
    Los valores por defecto son los del archivo de ejemplo de MACS.
    """

    fondo = models.OneToOneField(FondoEmpleado, on_delete=models.CASCADE, related_name="siigo")
    activo = models.BooleanField(default=True)
    empresa = models.CharField(
        max_length=200, default="MACS COMERCIALIZADORA Y DISTRIBUIDORA S.A.S",
        help_text="Razón social que aparece en el encabezado del archivo.",
    )
    tipo_comprobante = models.CharField(max_length=1, default="F", help_text="F = factura de venta.")
    codigo_comprobante = models.PositiveIntegerField(default=3)
    siguiente_numero = models.PositiveIntegerField(
        "próximo número de factura", default=1,
        help_text="Consecutivo de Siigo que recibirá el próximo pedido exportado. Se actualiza solo.",
    )
    vendedor = models.PositiveIntegerField("código del vendedor", default=500)
    ciudad = models.PositiveIntegerField("código de la ciudad", default=666)
    zona = models.PositiveIntegerField("código de la zona", default=161)
    centro_costo = models.PositiveIntegerField("centro de costo", default=1)
    subcentro_costo = models.PositiveIntegerField("subcentro de costo", default=1)
    sucursal = models.PositiveIntegerField(default=0)
    bodega = models.PositiveIntegerField(
        "bodega por defecto", default=1, help_text="Se usa si el producto no tiene su propia bodega Siigo.",
    )
    forma_pago = models.PositiveIntegerField("forma de pago", default=3)
    dias_vencimiento = models.PositiveIntegerField(
        "días de vencimiento", default=0, help_text="Plazo de la cuenta por cobrar. 0 = vence el mismo día.",
    )
    # La cuenta de ingresos depende de la línea/grupo del producto (tabla "Cuentas de venta por línea
    # Siigo"); esta se usa solo para los productos cuya línea no está en esa tabla.
    cuenta_ingreso = models.PositiveBigIntegerField("cuenta de ingresos por defecto (crédito)", default=4135950400)
    cuenta_cartera = models.PositiveBigIntegerField("cuenta por cobrar (débito)", default=1365950100)
    cuenta_inventario = models.PositiveBigIntegerField("cuenta de inventario (crédito)", default=1435010400)
    cuenta_costo = models.PositiveBigIntegerField("cuenta de costo de ventas (débito)", default=6135950400)
    cuenta_descuento = models.PositiveBigIntegerField("cuenta de descuento a empleados (débito)", default=4135980000)

    class Meta:
        verbose_name = "Configuración de Siigo"
        verbose_name_plural = "Configuración de Siigo"

    def __str__(self):
        return f"Siigo · {self.fondo}"

    @property
    def comprobante(self):
        return f"{self.tipo_comprobante}-{self.codigo_comprobante:03d}"


validar_cuenta = RegexValidator(r"^\d{1,10}$", "Escribe solo números (hasta 10 dígitos).")


def cuenta_siigo(texto):
    """Cuenta como la usa la factura de Siigo: 10 dígitos, completando con ceros (41359504 -> 4135950400)."""
    digitos = "".join(c for c in str(texto or "") if c.isdigit())
    return int(digitos.ljust(10, "0")) if digitos.strip("0") else None


class CuentaLineaSiigo(models.Model):
    """
    Cuenta de venta (ingreso) de Siigo por línea y grupo de producto (la tabla de líneas de Siigo).
    El código Siigo del producto 700-15-45 usa la fila línea 700 / grupo 15.
    """

    linea = models.PositiveIntegerField("línea")
    grupo = models.PositiveIntegerField()
    nombre_linea = models.CharField("nombre de la línea", max_length=100, blank=True)
    cuenta_venta = models.CharField("cta. venta", max_length=10, validators=[validar_cuenta])

    class Meta:
        verbose_name = "Cuenta de venta por línea Siigo"
        verbose_name_plural = "Cuentas de venta por línea Siigo"
        ordering = ["linea", "grupo"]
        constraints = [models.UniqueConstraint(fields=["linea", "grupo"], name="cuenta_linea_siigo_unica")]

    def __str__(self):
        return f"{self.linea:03d}-{self.grupo:04d} {self.nombre_linea}".strip()


class Finca(models.Model):
    """
    Punto de entrega de un fondo (finca, sede o planta). Quien compra por nómina
    elige su finca para que el pedido se entregue exactamente ahí.
    """

    fondo = models.ForeignKey(FondoEmpleado, on_delete=models.CASCADE, related_name="fincas")
    nombre = models.CharField(max_length=150)
    municipio = models.CharField(max_length=120, blank=True)
    indicaciones = models.TextField(
        blank=True,
        help_text="Cómo llegar y a quién entregar (vereda, portería, horario de recibo...).",
    )
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Finca / punto de entrega"
        verbose_name_plural = "Fincas / puntos de entrega"
        ordering = ["fondo", "orden", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["fondo", "nombre"], name="finca_nombre_unico_por_fondo"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.municipio})" if self.municipio else self.nombre


class AfiliadoFondo(models.Model):
    """Registro del padrón de afiliados/empleados que el fondo carga a la plataforma."""

    fondo = models.ForeignKey(
        FondoEmpleado,
        on_delete=models.CASCADE,
        related_name="afiliados",
    )
    documento = TextoCifrado(
        help_text="Cifrado en la base de datos. Normalizado: solo dígitos y letras.",
    )
    documento_huella = models.CharField(
        max_length=64,
        editable=False,
        db_index=True,
        help_text="Huella HMAC del documento para buscarlo sin guardarlo en claro.",
    )
    nombre = models.CharField(max_length=200, blank=True)
    empresa = models.CharField(max_length=200, blank=True)
    cupo_disponible = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    activo = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Afiliado del fondo"
        verbose_name_plural = "Padrón de afiliados"
        ordering = ["fondo", "documento"]
        constraints = [
            models.UniqueConstraint(
                fields=["fondo", "documento_huella"],
                name="afiliado_documento_unico_por_fondo",
            ),
            models.CheckConstraint(
                condition=models.Q(cupo_disponible__gte=0),
                name="afiliado_cupo_no_negativo",
            ),
        ]

    def save(self, *args, **kwargs):
        self.documento = normalizar_documento(self.documento)
        self.documento_huella = huella(self.documento)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nombre or 'Afiliado'} ({self.fondo})"


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

    ORIGEN_AUTOMATICO = "AUTOMATICO"
    ORIGEN_GESTOR = "GESTOR"

    ORIGENES = [
        (ORIGEN_AUTOMATICO, "Automática (verificación del fondo)"),
        (ORIGEN_GESTOR, "Gestor del fondo"),
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
    finca = models.ForeignKey(
        Finca,
        on_delete=models.PROTECT,
        related_name="solicitudes",
        null=True,
        blank=True,
        help_text="Finca o punto donde se entrega el pedido.",
    )
    afiliado = models.ForeignKey(
        AfiliadoFondo,
        on_delete=models.SET_NULL,
        related_name="solicitudes",
        null=True,
        blank=True,
    )

    nombre_completo = models.CharField(max_length=200)
    # Datos sensibles cifrados en reposo (Ley 1581 de 2012).
    documento = TextoCifrado()
    documento_huella = models.CharField(max_length=64, editable=False, db_index=True, blank=True)
    telefono = TextoCifrado(blank=True)
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
    cupo_reservado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Cupo descontado del padrón; se devuelve si el pedido se cancela.",
    )
    verificacion_mensaje = models.TextField(
        blank=True,
        help_text="Resultado de la verificación automática (padrón o API).",
    )
    origen_decision = models.CharField(max_length=15, choices=ORIGENES, blank=True)
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="solicitudes_decididas",
        null=True,
        blank=True,
    )
    respuesta_fondo = models.TextField(blank=True)
    observaciones_usuario = models.TextField(blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default=ESTADO_PENDIENTE)

    # Autorización de tratamiento de datos (prueba de la autorización, art. 9 Ley 1581).
    autorizacion_datos = models.BooleanField(default=False)
    autorizacion_fecha = models.DateTimeField(blank=True, null=True)
    autorizacion_version = models.CharField(
        max_length=20,
        blank=True,
        help_text="Versión de la política de tratamiento de datos que aceptó el titular.",
    )
    corte = models.ForeignKey(
        "CorteNomina",
        on_delete=models.PROTECT,
        related_name="solicitudes",
        null=True,
        blank=True,
        help_text="Corte mensual en que se reportó al fondo para descontar por nómina.",
    )
    anonimizada_en = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Fecha en que se borraron los datos personales por la política de retención.",
    )

    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_respuesta = models.DateTimeField(blank=True, null=True)
    referencia_fondo = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "Solicitud de descuento por nómina"
        verbose_name_plural = "Solicitudes de descuento por nómina"
        ordering = ["-fecha_solicitud"]
        indexes = [
            models.Index(fields=["fondo", "estado"]),
        ]

    def __str__(self):
        return f"Solicitud #{self.id} - {self.nombre_completo}"

    @property
    def esta_pendiente(self):
        return self.estado == self.ESTADO_PENDIENTE

    @property
    def documento_enmascarado(self):
        return enmascarar(normalizar_documento(self.documento))

    def save(self, *args, **kwargs):
        self.documento_huella = huella(self.documento)
        super().save(*args, **kwargs)


class HistorialSolicitud(models.Model):
    """Bitácora de auditoría: cada verificación y decisión queda registrada."""

    EVENTO_CREADA = "CREADA"
    EVENTO_VERIFICACION = "VERIFICACION"
    EVENTO_DECISION = "DECISION"
    EVENTO_CUPO_LIBERADO = "CUPO_LIBERADO"

    EVENTOS = [
        (EVENTO_CREADA, "Solicitud creada"),
        (EVENTO_VERIFICACION, "Verificación de vinculación"),
        (EVENTO_DECISION, "Decisión"),
        (EVENTO_CUPO_LIBERADO, "Cupo liberado"),
    ]

    solicitud = models.ForeignKey(
        SolicitudDescuentoNomina,
        on_delete=models.CASCADE,
        related_name="historial",
    )
    evento = models.CharField(max_length=20, choices=EVENTOS)
    estado = models.CharField(max_length=20, blank=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    detalle = models.JSONField(default=dict, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Historial de solicitud"
        verbose_name_plural = "Historial de solicitudes"
        ordering = ["fecha", "id"]

    def __str__(self):
        return f"#{self.solicitud_id} {self.get_evento_display()} {self.fecha:%Y-%m-%d %H:%M}"


class CorteNomina(models.Model):
    """
    Cierre mensual por fondo: agrupa las solicitudes aprobadas que el fondo debe
    descontar por nómina. Una solicitud solo puede quedar en un corte, así nunca
    se reporta (ni se descuenta) dos veces.
    """

    fondo = models.ForeignKey(FondoEmpleado, on_delete=models.PROTECT, related_name="cortes")
    periodo = models.DateField(help_text="Primer día del mes del corte.")
    cantidad = models.PositiveIntegerField(default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    generado_en = models.DateTimeField(auto_now_add=True)
    generado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cortes_nomina",
    )
    enviado_en = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Corte de nómina"
        verbose_name_plural = "Cortes de nómina"
        ordering = ["-periodo", "fondo__nombre"]
        constraints = [
            models.UniqueConstraint(fields=["fondo", "periodo"], name="corte_unico_por_fondo_y_mes"),
        ]

    def __str__(self):
        return f"{self.fondo} · {self.periodo:%Y-%m}"
