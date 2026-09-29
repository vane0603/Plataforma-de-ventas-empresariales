from django.contrib import admin

from .models import Combo


@admin.register(Combo)
class ComboAdmin(admin.ModelAdmin):

    list_display = (
        "codigo",
        "nombre",
        "precio",
        "precio_anterior",
        "stock",
        "destacado",
        "activo",
        "orden",
        "created_at",
    )

    list_filter = (
        "activo",
        "destacado",
        "created_at",
    )

    search_fields = (
        "codigo",
        "nombre",
        "descripcion",
    )

    list_editable = (
        "precio",
        "precio_anterior",
        "stock",
        "destacado",
        "activo",
        "orden",
    )

    ordering = (
        "orden",
        "nombre",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (

        (
            "Información del combo",
            {
                "fields": (
                    "codigo",
                    "nombre",
                    "descripcion",
                    "imagen",
                )
            },
        ),

        (
            "Información comercial",
            {
                "fields": (
                    "precio_anterior",
                    "precio",
                    "stock",
                )
            },
        ),

        (
            "Estado y visualización",
            {
                "fields": (
                    "destacado",
                    "activo",
                    "orden",
                )
            },
        ),

        (
            "Auditoría",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),

    )