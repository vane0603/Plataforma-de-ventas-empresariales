from django.contrib import admin, messages

from .models import Notificacion
from .services import enviar


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "evento", "canal", "estado", "pedido", "solicitud", "intentos", "enviada_en")
    list_filter = ("estado", "canal", "evento", "created_at")
    search_fields = ("pedido__numero", "solicitud__id", "id_externo")
    list_select_related = ("pedido", "solicitud")
    readonly_fields = [f.name for f in Notificacion._meta.fields]
    actions = ["reenviar"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Reenviar las notificaciones seleccionadas")
    def reenviar(self, request, queryset):
        resultado = [enviar(n).estado for n in queryset]
        enviadas = resultado.count(Notificacion.ESTADO_ENVIADA)
        nivel = messages.SUCCESS if enviadas == len(resultado) else messages.WARNING
        self.message_user(request, f"Enviadas {enviadas} de {len(resultado)}.", nivel)
