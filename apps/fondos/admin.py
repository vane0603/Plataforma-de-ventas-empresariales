from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path

from apps.core.cifrado import huella

from .models import (
    AfiliadoFondo, ConfiguracionSiigo, CorteNomina, CuentaLineaSiigo, Finca, FondoEmpleado, HistorialSolicitud,
    SolicitudDescuentoNomina,
)
from .siigo_cuentas import ImportacionError, importar_cuentas_lineas


class ImportarCuentasForm(forms.Form):
    archivo = forms.FileField(label="Archivo Excel (.xlsx) con la tabla de líneas de Siigo")


@admin.register(CuentaLineaSiigo)
class CuentaLineaSiigoAdmin(admin.ModelAdmin):
    list_display = ("linea_grupo", "nombre_linea", "cuenta_venta")
    list_editable = ("cuenta_venta",)
    list_display_links = ("linea_grupo",)
    list_filter = ("linea", "nombre_linea")
    search_fields = ("nombre_linea", "linea", "grupo")
    list_per_page = 100
    change_list_template = "admin/fondos/cuentalineasiigo/change_list.html"

    @admin.display(description="Línea - grupo", ordering="linea")
    def linea_grupo(self, obj):
        return f"{obj.linea:03d} - {obj.grupo:04d}"

    def get_urls(self):
        return [
            path("importar/", self.admin_site.admin_view(self.importar), name="fondos_cuentalineasiigo_importar"),
        ] + super().get_urls()

    def importar(self, request):
        if not self.has_add_permission(request) or not self.has_change_permission(request):
            raise PermissionDenied
        form = ImportarCuentasForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            try:
                resultado = importar_cuentas_lineas(form.cleaned_data["archivo"])
            except ImportacionError as exc:
                form.add_error("archivo", str(exc))
            else:
                messages.success(
                    request,
                    f"Tabla importada: {resultado.creadas} líneas nuevas y {resultado.actualizadas} actualizadas.",
                )
                for error in resultado.errores[:10]:
                    messages.warning(request, error)
                return redirect("admin:fondos_cuentalineasiigo_changelist")
        return TemplateResponse(request, "admin/fondos/cuentalineasiigo/importar.html", {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Importar cuentas de venta por línea desde Excel",
            "form": form,
        })


class FincaInline(admin.TabularInline):
    model = Finca
    extra = 1
    fields = ("nombre", "municipio", "indicaciones", "activo", "orden")


class ConfiguracionSiigoInline(admin.StackedInline):
    model = ConfiguracionSiigo
    extra = 0
    max_num = 1
    can_delete = False
    verbose_name_plural = "Exportación a Siigo (solo si este fondo factura en Siigo)"
    fieldsets = (
        (None, {"fields": ("activo", "empresa", ("tipo_comprobante", "codigo_comprobante", "siguiente_numero"))}),
        ("Códigos", {"fields": (("vendedor", "ciudad", "zona"), ("centro_costo", "subcentro_costo", "sucursal"),
                                ("bodega", "forma_pago", "dias_vencimiento"))}),
        ("Cuentas contables", {"fields": (("cuenta_ingreso", "cuenta_cartera"), ("cuenta_inventario", "cuenta_costo"), "cuenta_descuento"),
                               "description": "La cuenta de ingresos de cada producto se toma de <b>Cuentas de venta por línea Siigo</b> "
                                              "según su línea y grupo; la de aquí se usa solo si la línea no está en esa tabla."}),
    )


@admin.register(Finca)
class FincaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "municipio", "fondo", "activo", "orden")
    list_filter = ("fondo", "activo")
    list_editable = ("activo", "orden")
    search_fields = ("nombre", "municipio")


@admin.register(FondoEmpleado)
class FondoEmpleadoAdmin(admin.ModelAdmin):
    inlines = [FincaInline, ConfiguracionSiigoInline]
    list_display = ("nombre", "nit", "modo_verificacion", "decision_automatica", "correo", "activo")
    list_filter = ("activo", "modo_verificacion", "decision_automatica")
    search_fields = ("nombre", "nit", "responsable", "correo")
    filter_horizontal = ("gestores",)
    fieldsets = (
        (None, {"fields": ("nombre", "nit", "correo", "telefono", "responsable", "activo", "observaciones")}),
        ("Descuento para empleados", {"fields": ("descuento_empleados",)}),
        ("Gestores", {"fields": ("gestores",)}),
        ("Verificación de vinculación", {
            "fields": ("modo_verificacion", "decision_automatica", "api_url", "api_token_env"),
        }),
    )


@admin.register(AfiliadoFondo)
class AfiliadoFondoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "empresa", "fondo", "cupo_disponible", "activo", "updated_at")
    list_filter = ("fondo", "activo")
    search_fields = ("nombre", "empresa")
    search_help_text = "Busca por nombre o empresa, o por número de documento exacto."
    list_select_related = ("fondo",)
    readonly_fields = ("documento_huella",)

    def get_search_results(self, request, queryset, search_term):
        resultado, duplicados = super().get_search_results(request, queryset, search_term)
        if search_term:
            resultado |= queryset.filter(documento_huella=huella(search_term))
        return resultado, duplicados


class HistorialSolicitudInline(admin.TabularInline):
    model = HistorialSolicitud
    extra = 0
    can_delete = False
    readonly_fields = ("fecha", "evento", "estado", "usuario", "detalle")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SolicitudDescuentoNomina)
class SolicitudDescuentoNominaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "nombre_completo",
        "documento_enmascarado",
        "fondo",
        "pedido",
        "valor_solicitado",
        "valor_aprobado",
        "estado",
        "origen_decision",
        "fecha_solicitud",
    )
    list_filter = ("estado", "origen_decision", "fondo", "finca", "fecha_solicitud")
    search_help_text = "Busca por nombre, correo, fondo, afiliado o pedido, o por número de documento exacto."
    search_fields = (
        "nombre_completo",
        "correo",
        "fondo__nombre",
        "numero_afiliado",
        "pedido__numero",
    )
    list_select_related = ("fondo", "pedido")
    # Las decisiones se registran solo desde el portal del fondo (services.aplicar_decision),
    # que reserva cupo, actualiza el pedido y deja auditoría.
    readonly_fields = (
        "usuario",
        "pedido",
        "afiliado",
        "valor_solicitado",
        "estado",
        "vinculacion_validada",
        "valor_aprobado",
        "cupo_disponible_reportado",
        "cupo_reservado",
        "verificacion_mensaje",
        "autorizacion_datos",
        "autorizacion_fecha",
        "autorizacion_version",
        "anonimizada_en",
        "corte",
        "origen_decision",
        "decidido_por",
        "fecha_solicitud",
        "fecha_respuesta",
    )
    inlines = [HistorialSolicitudInline]

    def get_search_results(self, request, queryset, search_term):
        resultado, duplicados = super().get_search_results(request, queryset, search_term)
        if search_term:
            resultado |= queryset.filter(documento_huella=huella(search_term))
        return resultado, duplicados


@admin.register(CorteNomina)
class CorteNominaAdmin(admin.ModelAdmin):
    list_display = ("fondo", "periodo", "cantidad", "total", "generado_en", "generado_por", "enviado_en")
    list_filter = ("fondo",)
    date_hierarchy = "periodo"
    readonly_fields = ("fondo", "periodo", "cantidad", "total", "generado_en", "generado_por", "enviado_en")

    def has_add_permission(self, request):
        return False
