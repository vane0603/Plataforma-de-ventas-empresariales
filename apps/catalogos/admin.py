from django.contrib import admin

from .models import (
    Categoria,
    Marca,
    UnidadMedida,
    Presentacion,
)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "activo",
        "orden",
    )

    list_filter = (
        "activo",
    )

    search_fields = (
        "nombre",
    )

    list_editable = (
        "activo",
        "orden",
    )

    ordering = (
        "orden",
        "nombre",
    )


@admin.register(Marca)
class MarcaAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "activo",
    )

    list_filter = (
        "activo",
    )

    search_fields = (
        "nombre",
    )

    list_editable = (
        "activo",
    )

    ordering = (
        "nombre",
    )


@admin.register(UnidadMedida)
class UnidadMedidaAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "abreviatura",
        "activo",
    )

    list_filter = (
        "activo",
    )

    search_fields = (
        "nombre",
        "abreviatura",
    )

    list_editable = (
        "abreviatura",
        "activo",
    )

    ordering = (
        "nombre",
    )


@admin.register(Presentacion)
class PresentacionAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "cantidad",
        "unidad",
        "activo",
    )

    list_filter = (
        "unidad",
        "activo",
    )

    search_fields = (
        "nombre",
    )

    list_editable = (
        "cantidad",
        "activo",
    )

    ordering = (
        "nombre",
    )