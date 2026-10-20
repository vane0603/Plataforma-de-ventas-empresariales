from rest_framework import serializers

from apps.carrito.models import CarritoItem
from apps.catalogos.models import Categoria
from apps.fondos.models import Finca, FondoEmpleado, SolicitudDescuentoNomina
from apps.pagos.services import pedido_pagable_en_linea
from apps.pedidos.models import Pedido, PedidoItem
from apps.productos.models import Producto, ProductoPresentacion
from apps.promociones.models import Combo


# ---------------------------------------------------------------- Catálogo

class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ["id", "nombre", "icono"]


class PresentacionSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(source="presentacion.nombre")

    class Meta:
        model = ProductoPresentacion
        fields = ["id", "codigo", "nombre", "precio"]


class ProductoSerializer(serializers.ModelSerializer):
    categoria = CategoriaSerializer()
    marca = serializers.CharField(source="marca.nombre")
    precio_desde = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    presentaciones = PresentacionSerializer(source="presentaciones_activas", many=True)

    class Meta:
        model = Producto
        fields = [
            "id", "codigo", "nombre", "descripcion", "categoria", "marca", "imagen",
            "destacado", "precio_desde", "presentaciones",
        ]


class ComboSerializer(serializers.ModelSerializer):
    class Meta:
        model = Combo
        fields = ["id", "codigo", "nombre", "descripcion", "imagen", "precio", "precio_anterior", "stock"]


# ---------------------------------------------------------------- Carrito

class CarritoItemSerializer(serializers.ModelSerializer):
    tipo = serializers.SerializerMethodField()
    objeto_id = serializers.SerializerMethodField()
    nombre = serializers.CharField(source="nombre_mostrar")
    detalle = serializers.CharField(source="detalle_mostrar")
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        model = CarritoItem
        fields = ["tipo", "objeto_id", "nombre", "detalle", "cantidad", "precio_unitario", "subtotal"]

    def get_tipo(self, item) -> str:
        return "c" if item.es_combo else "p"

    def get_objeto_id(self, item) -> int:
        return item.combo_id or item.presentacion_id


class CarritoSerializer(serializers.Serializer):
    items = CarritoItemSerializer(many=True)
    cantidad_total = serializers.IntegerField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    cantidad = serializers.IntegerField(required=False, help_text="Cantidad final del ítem modificado.")
    mensaje = serializers.CharField(required=False, help_text="Aviso, p. ej. si se ajustó por stock.")


class CantidadSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=[("p", "Presentación de producto"), ("c", "Combo")])
    id = serializers.IntegerField(min_value=1)
    cantidad = serializers.IntegerField(min_value=0, max_value=99, help_text="0 elimina el ítem.")


# ---------------------------------------------------------------- Pedidos

class PedidoItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PedidoItem
        fields = ["producto_nombre", "referencia", "presentacion", "cantidad", "precio_unitario", "subtotal"]


class PedidoSerializer(serializers.ModelSerializer):
    estado_display = serializers.CharField(source="get_estado_display")
    items = PedidoItemSerializer(many=True)
    saldo_pendiente = serializers.DecimalField(max_digits=12, decimal_places=2)
    puede_cancelarse = serializers.BooleanField()
    requiere_definir_saldo = serializers.BooleanField()
    pago_en_linea_disponible = serializers.SerializerMethodField()
    solicitud_nomina = serializers.SerializerMethodField()

    class Meta:
        model = Pedido
        fields = [
            "id", "numero", "estado", "estado_display", "metodo_pago", "metodo_pago_saldo",
            "total", "valor_nomina", "saldo_pendiente", "direccion_entrega", "ciudad",
            "observaciones", "created_at", "items", "puede_cancelarse",
            "requiere_definir_saldo", "pago_en_linea_disponible", "solicitud_nomina",
        ]

    def get_pago_en_linea_disponible(self, pedido) -> bool:
        return pedido_pagable_en_linea(pedido)

    def get_solicitud_nomina(self, pedido) -> int | None:
        solicitud = getattr(pedido, "solicitud_nomina", None)
        return solicitud.id if solicitud else None


class PedidoCreadoSerializer(PedidoSerializer):
    """Respuesta al crear: incluye el código de seguimiento (lo necesita el invitado)."""

    class Meta(PedidoSerializer.Meta):
        fields = PedidoSerializer.Meta.fields + ["codigo_acceso"]


class CheckoutSerializer(serializers.Serializer):
    """Solo documenta la entrada; la validación la hace pedidos.forms.CheckoutForm."""

    metodo_pago = serializers.ChoiceField(choices=Pedido.METODOS_PAGO)
    direccion_entrega = serializers.CharField(required=False, help_text="Obligatoria salvo con NOMINA (se entrega en la finca).")
    ciudad = serializers.CharField(required=False, help_text="Obligatoria salvo con NOMINA.")
    observaciones = serializers.CharField(required=False, allow_blank=True)
    nombre = serializers.CharField(required=False, help_text="Obligatorio sin sesión.")
    correo = serializers.EmailField(required=False, help_text="Obligatorio sin sesión.")
    telefono = serializers.CharField(required=False, help_text="Obligatorio sin sesión.")
    autoriza_tratamiento = serializers.BooleanField(
        required=False, help_text="Obligatorio sin sesión: autorización de datos (Ley 1581)."
    )


# ---------------------------------------------------------------- Nómina

class FincaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Finca
        fields = ["id", "nombre", "municipio", "indicaciones"]


class FondoSerializer(serializers.ModelSerializer):
    class Meta:
        model = FondoEmpleado
        fields = ["id", "nombre"]


class FondoConFincasSerializer(FondoSerializer):
    fincas = serializers.SerializerMethodField()

    class Meta(FondoSerializer.Meta):
        fields = FondoSerializer.Meta.fields + ["fincas"]

    def get_fincas(self, fondo) -> list[dict]:
        activas = [f for f in fondo.fincas.all() if f.activo]
        return FincaSerializer(activas, many=True).data


class SolicitudSerializer(serializers.ModelSerializer):
    fondo = FondoSerializer()
    finca = FincaSerializer(allow_null=True)
    pedido = serializers.CharField(source="pedido.numero", default="")
    estado_display = serializers.CharField(source="get_estado_display")

    class Meta:
        model = SolicitudDescuentoNomina
        fields = [
            "id", "fondo", "finca", "pedido", "estado", "estado_display", "valor_solicitado",
            "valor_aprobado", "respuesta_fondo", "fecha_solicitud", "fecha_respuesta",
        ]


class SolicitudEntradaSerializer(serializers.Serializer):
    """Solo documenta la entrada; la validación la hace fondos.forms.SolicitudDescuentoNominaForm."""

    pedido = serializers.IntegerField()
    fondo = serializers.IntegerField()
    finca = serializers.IntegerField(required=False, help_text="Obligatoria si el fondo tiene fincas (GET nomina/fondos/).")
    nombre_completo = serializers.CharField()
    documento = serializers.CharField()
    telefono = serializers.CharField(required=False)
    correo = serializers.EmailField(required=False)
    empresa = serializers.CharField()
    numero_afiliado = serializers.CharField(required=False)
    observaciones_usuario = serializers.CharField(required=False)
    autoriza_tratamiento = serializers.BooleanField(help_text="Debe ser true (Ley 1581 de 2012).")


class ResultadoPadronSerializer(serializers.Serializer):
    creados = serializers.IntegerField()
    actualizados = serializers.IntegerField()
    desactivados = serializers.IntegerField()
    errores = serializers.ListField(child=serializers.CharField())


class CorteSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    periodo = serializers.CharField()
    cantidad = serializers.IntegerField()
    total = serializers.DecimalField(max_digits=14, decimal_places=2)


class SolicitudGestorSerializer(SolicitudSerializer):
    """Vista del fondo: incluye los datos que necesita para verificar al solicitante."""

    class Meta(SolicitudSerializer.Meta):
        fields = SolicitudSerializer.Meta.fields + [
            "nombre_completo", "documento", "telefono", "correo", "empresa", "numero_afiliado",
            "vinculacion_validada", "cupo_disponible_reportado", "verificacion_mensaje",
            "origen_decision", "referencia_fondo",
        ]


ESTADOS_DECISION = [
    c for c in SolicitudDescuentoNomina.ESTADOS if c[0] != SolicitudDescuentoNomina.ESTADO_PENDIENTE
]


class DecisionSerializer(serializers.Serializer):
    """Solo documenta la entrada; la validación la hace fondos.forms.RespuestaFondoForm."""

    vinculacion_validada = serializers.BooleanField()
    estado = serializers.ChoiceField(choices=ESTADOS_DECISION)
    cupo_disponible_reportado = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    valor_aprobado = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    referencia_fondo = serializers.CharField(required=False)
    respuesta_fondo = serializers.CharField(required=False)


class ReporteSerializer(serializers.Serializer):
    fondo = FondoSerializer()
    periodo = serializers.CharField()
    cerrado = serializers.BooleanField()
    cantidad = serializers.IntegerField()
    total = serializers.DecimalField(max_digits=14, decimal_places=2)
    solicitudes = SolicitudGestorSerializer(many=True)
