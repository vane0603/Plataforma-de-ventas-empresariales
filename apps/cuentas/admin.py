from django.contrib import admin

from .models import AutorizacionDatos


@admin.register(AutorizacionDatos)
class AutorizacionDatosAdmin(admin.ModelAdmin):
    """Solo lectura: es la prueba de que el titular autorizó."""

    list_display = ("fecha", "origen", "usuario", "pedido", "version_politica")
    list_filter = ("origen", "version_politica")
    search_fields = ("usuario__username", "usuario__email", "pedido__numero")
    date_hierarchy = "fecha"
    readonly_fields = ("usuario", "pedido", "origen", "version_politica", "fecha")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
