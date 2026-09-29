from django.contrib import admin
from .models import Pedido, PedidoItem


class PedidoItemInline(admin.TabularInline):
    model = PedidoItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "producto_presentacion",
        "producto_nombre",
        "referencia",
        "presentacion",
        "cantidad",
        "precio_unitario",
        "subtotal",
    )


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = (
        "numero",
        "usuario",
        "metodo_pago",
        "estado",
        "total",
        "ciudad",
        "created_at",
    )
    list_filter = ("metodo_pago", "estado", "created_at")
    search_fields = ("numero", "usuario__username", "usuario__email")
    readonly_fields = ("numero", "carrito", "subtotal", "total", "created_at", "updated_at")
    inlines = [PedidoItemInline]


@admin.register(PedidoItem)
class PedidoItemAdmin(admin.ModelAdmin):
    list_display = ("pedido", "producto_nombre", "presentacion", "cantidad", "subtotal")
    search_fields = ("pedido__numero", "producto_nombre", "referencia")
