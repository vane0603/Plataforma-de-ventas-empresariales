from django.contrib import admin
from .models import Entrega, Pedido, PedidoItem, PuntoRecogida


class PedidoItemInline(admin.TabularInline):
    model = PedidoItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "producto_presentacion",
        "combo",
        "producto_nombre",
        "referencia",
        "presentacion",
        "cantidad",
        "precio_unitario",
        "subtotal",
    )


class EntregaInline(admin.StackedInline):
    model = Entrega
    extra = 0
    can_delete = False
    readonly_fields = ("entregado_en", "entregado_por", "recibido_por", "firma", "observaciones")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PuntoRecogida)
class PuntoRecogidaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "direccion", "ciudad", "horario", "activo", "orden")
    list_editable = ("activo", "orden")
    search_fields = ("nombre", "direccion", "ciudad")


@admin.register(Entrega)
class EntregaAdmin(admin.ModelAdmin):
    list_display = ("pedido", "entregado_en", "recibido_por", "entregado_por")
    search_fields = ("pedido__numero", "recibido_por")
    date_hierarchy = "entregado_en"
    readonly_fields = ("pedido", "entregado_en", "entregado_por", "recibido_por", "firma", "observaciones")

    def has_add_permission(self, request):
        return False


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = (
        "numero",
        "usuario",
        "nombre_contacto",
        "metodo_pago",
        "estado",
        "total",
        "valor_nomina",
        "ciudad",
        "created_at",
    )
    list_filter = ("metodo_pago", "estado", "tipo_entrega", "punto_recogida", "created_at")
    search_fields = ("numero", "usuario__username", "usuario__email", "correo_contacto", "nombre_contacto", "telefono_contacto")
    readonly_fields = (
        "numero",
        "carrito",
        "subtotal",
        "total",
        "valor_nomina",
        "metodo_pago_saldo",
        "created_at",
        "updated_at",
    )
    list_select_related = ("usuario",)
    inlines = [PedidoItemInline, EntregaInline]


@admin.register(PedidoItem)
class PedidoItemAdmin(admin.ModelAdmin):
    list_display = ("pedido", "producto_nombre", "presentacion", "cantidad", "subtotal")
    search_fields = ("pedido__numero", "producto_nombre", "referencia")
