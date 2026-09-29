from decimal import Decimal

from django import forms

from .models import FondoEmpleado, SolicitudDescuentoNomina


class SolicitudDescuentoNominaForm(forms.ModelForm):
    class Meta:
        model = SolicitudDescuentoNomina
        fields = [
            "fondo",
            "nombre_completo",
            "documento",
            "telefono",
            "correo",
            "empresa",
            "numero_afiliado",
            "observaciones_usuario",
        ]
        widgets = {
            "fondo": forms.Select(attrs={"class": "form-select"}),
            "nombre_completo": forms.TextInput(attrs={"class": "form-control", "autocomplete": "name"}),
            "documento": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "telefono": forms.TextInput(attrs={"class": "form-control", "autocomplete": "tel"}),
            "correo": forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
            "empresa": forms.TextInput(attrs={"class": "form-control"}),
            "numero_afiliado": forms.TextInput(attrs={"class": "form-control"}),
            "observaciones_usuario": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }
        labels = {
            "fondo": "Fondo de empleados",
            "nombre_completo": "Nombre completo",
            "documento": "Número de documento",
            "telefono": "Teléfono",
            "correo": "Correo electrónico",
            "empresa": "Empresa donde trabaja",
            "numero_afiliado": "Número de afiliado (opcional)",
            "observaciones_usuario": "Observaciones",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fondo"].queryset = FondoEmpleado.objects.filter(activo=True).order_by("nombre")
        self.fields["fondo"].required = True
        self.fields["nombre_completo"].required = True
        self.fields["documento"].required = True
        self.fields["empresa"].required = True

    def clean_nombre_completo(self):
        nombre = " ".join((self.cleaned_data.get("nombre_completo") or "").strip().split())
        if len(nombre) < 5:
            raise forms.ValidationError("Ingrese su nombre completo.")
        return nombre

    def clean_documento(self):
        documento = (self.cleaned_data.get("documento") or "").strip()
        if not documento:
            raise forms.ValidationError("Debe ingresar su número de documento.")
        if not all(c in "0123456789.-" for c in documento):
            raise forms.ValidationError("El número de documento contiene caracteres no válidos.")
        return documento

    def clean_empresa(self):
        empresa = " ".join((self.cleaned_data.get("empresa") or "").strip().split())
        if not empresa:
            raise forms.ValidationError("Debe ingresar la empresa donde trabaja.")
        return empresa


class RespuestaFondoForm(forms.ModelForm):
    class Meta:
        model = SolicitudDescuentoNomina
        fields = [
            "vinculacion_validada",
            "estado",
            "cupo_disponible_reportado",
            "valor_aprobado",
            "referencia_fondo",
            "respuesta_fondo",
        ]
        widgets = {
            "vinculacion_validada": forms.Select(
                choices=(("", "Seleccione"), ("True", "Sí"), ("False", "No")),
                attrs={"class": "form-select"},
            ),
            "estado": forms.Select(attrs={"class": "form-select"}),
            "cupo_disponible_reportado": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
            "valor_aprobado": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
            "referencia_fondo": forms.TextInput(attrs={"class": "form-control"}),
            "respuesta_fondo": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }
        labels = {
            "vinculacion_validada": "¿La persona trabaja/está afiliada con la entidad?",
            "estado": "Decisión",
            "cupo_disponible_reportado": "Cupo disponible",
            "valor_aprobado": "Valor aprobado",
            "referencia_fondo": "Referencia interna del fondo",
            "respuesta_fondo": "Observaciones del fondo",
        }

    def clean(self):
        cleaned = super().clean()
        vinculacion = cleaned.get("vinculacion_validada")
        estado = cleaned.get("estado")
        cupo = cleaned.get("cupo_disponible_reportado")
        aprobado = cleaned.get("valor_aprobado")
        solicitado = self.instance.valor_solicitado or Decimal("0")

        if vinculacion is None:
            self.add_error("vinculacion_validada", "Debe validar la vinculación del solicitante.")

        if estado == SolicitudDescuentoNomina.ESTADO_PENDIENTE:
            self.add_error("estado", "Debe registrar una decisión final.")

        if vinculacion is False and estado != SolicitudDescuentoNomina.ESTADO_RECHAZADA:
            self.add_error("estado", "Si la persona no está vinculada, la solicitud debe rechazarse.")

        if estado in (
            SolicitudDescuentoNomina.ESTADO_APROBADA,
            SolicitudDescuentoNomina.ESTADO_APROBADA_PARCIAL,
        ):
            if vinculacion is not True:
                self.add_error("vinculacion_validada", "La vinculación debe estar validada para aprobar.")
            if cupo is None:
                self.add_error("cupo_disponible_reportado", "Informe el cupo disponible.")
            if aprobado is None or aprobado <= 0:
                self.add_error("valor_aprobado", "Informe un valor aprobado mayor a cero.")
            elif aprobado > solicitado:
                self.add_error("valor_aprobado", "El valor aprobado no puede superar el valor solicitado.")
            elif cupo is not None and aprobado > cupo:
                self.add_error("valor_aprobado", "El valor aprobado no puede superar el cupo reportado.")

        if estado == SolicitudDescuentoNomina.ESTADO_APROBADA and aprobado != solicitado:
            self.add_error("valor_aprobado", "Para aprobación total, el valor aprobado debe ser igual al solicitado.")

        if estado == SolicitudDescuentoNomina.ESTADO_APROBADA_PARCIAL and aprobado is not None:
            if aprobado >= solicitado:
                self.add_error("valor_aprobado", "Para aprobación parcial, el valor debe ser menor al solicitado.")

        if estado == SolicitudDescuentoNomina.ESTADO_RECHAZADA:
            cleaned["valor_aprobado"] = Decimal("0")

        return cleaned
