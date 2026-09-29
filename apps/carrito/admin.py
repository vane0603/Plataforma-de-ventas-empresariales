from django.contrib import admin

from .models import Carrito, CarritoItem


class CarritoItemInline(admin.TabularInline):

    model = CarritoItem

    extra = 0

    readonly_fields = (
        "precio_unitario",
        "subtotal",
    )


@admin.register(Carrito)
class CarritoAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "usuario",
        "session_key",
        "activo",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "activo",
        "created_at",
    )

    search_fields = (
        "usuario__username",
        "usuario__email",
        "session_key",
    )

    inlines = [
        CarritoItemInline,
    ]


@admin.register(CarritoItem)
class CarritoItemAdmin(admin.ModelAdmin):

    list_display = (
        "carrito",
        "presentacion",
        "cantidad",
        "precio_unitario",
        "subtotal",
    )

    search_fields = (
        "presentacion__producto__nombre",
        "presentacion__codigo",
    )
