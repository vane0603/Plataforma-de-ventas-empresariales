from django.contrib import admin

from .models import Producto, ProductoPresentacion


class ProductoPresentacionInline(admin.TabularInline):

    model = ProductoPresentacion

    extra = 1

    fields = (
        "codigo",
        "presentacion",
        "precio",
        "activo",
        "destacado",
        "orden",
    )


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):

    list_display = (
        "codigo",
        "nombre",
        "categoria",
        "marca",
        "destacado",
        "activo",
    )

    list_filter = (
        "categoria",
        "marca",
        "destacado",
        "activo",
    )

    search_fields = (
        "codigo",
        "nombre",
        "descripcion",
    )

    list_editable = (
        "destacado",
        "activo",
    )

    inlines = [
        ProductoPresentacionInline,
    ]

    ordering = (
        "orden",
        "nombre",
    )


@admin.register(ProductoPresentacion)
class ProductoPresentacionAdmin(admin.ModelAdmin):

    list_display = (
        "codigo",
        "producto",
        "presentacion",
        "precio",
        "destacado",
        "activo",
    )

    list_filter = (
        "presentacion",
        "destacado",
        "activo",
    )

    search_fields = (
        "codigo",
        "producto__codigo",
        "producto__nombre",
    )

    list_editable = (
        "precio",
        "destacado",
        "activo",
    )

    ordering = (
        "orden",
        "codigo",
    )