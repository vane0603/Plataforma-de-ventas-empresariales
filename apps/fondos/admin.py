from django.contrib import admin

from .models import FondoEmpleado, SolicitudDescuentoNomina
from .services import notificar_usuario_respuesta


@admin.register(FondoEmpleado)
class FondoEmpleadoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "nit", "responsable", "correo", "telefono", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "nit", "responsable", "correo")
    filter_horizontal = ("gestores",)


@admin.register(SolicitudDescuentoNomina)
class SolicitudDescuentoNominaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "nombre_completo",
        "documento",
        "fondo",
        "pedido",
        "valor_solicitado",
        "valor_aprobado",
        "cupo_disponible_reportado",
        "estado",
        "fecha_solicitud",
        "fecha_respuesta",
    )
    list_filter = ("estado", "fondo", "empresa", "fecha_solicitud")
    search_fields = (
        "nombre_completo",
        "documento",
        "correo",
        "fondo__nombre",
        "numero_afiliado",
        "pedido__numero",
    )
    readonly_fields = (
        "usuario",
        "pedido",
        "valor_solicitado",
        "fecha_solicitud",
        "fecha_respuesta",
    )

    def save_model(self, request, obj, form, change):
        estado_anterior = None
        if change and obj.pk:
            estado_anterior = (
                SolicitudDescuentoNomina.objects
                .filter(pk=obj.pk)
                .values_list("estado", flat=True)
                .first()
            )
        super().save_model(request, obj, form, change)
        if (
            estado_anterior == SolicitudDescuentoNomina.ESTADO_PENDIENTE
            and obj.estado != SolicitudDescuentoNomina.ESTADO_PENDIENTE
        ):
            notificar_usuario_respuesta(obj)
