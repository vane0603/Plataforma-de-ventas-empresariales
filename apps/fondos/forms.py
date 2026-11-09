from decimal import Decimal

from django import forms

from .models import Finca, FondoEmpleado, SolicitudDescuentoNomina


class SelectFinca(forms.Select):
    """Cada opción lleva su fondo (data-fondo) para filtrar la lista en el navegador."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcion = super().create_option(name, value, label, selected, index, subindex, attrs)
        instancia = getattr(value, "instance", None)
        if instancia is not None:
            opcion["attrs"]["data-fondo"] = instancia.fondo_id
            if instancia.indicaciones:
                opcion["attrs"]["title"] = instancia.indicaciones
        return opcion


class SolicitudDescuentoNominaForm(forms.ModelForm):
    # Autorización previa, expresa e informada (Ley 1581 de 2012, art. 9).
    autoriza_tratamiento = forms.BooleanField(
        required=True,
        label="Autorizo el tratamiento de mis datos personales",
        error_messages={
            "required": "Para solicitar el descuento por nómina debes autorizar el tratamiento de tus datos."
        },
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    class Meta:
        model = SolicitudDescuentoNomina
        fields = [
            "fondo",
            "finca",
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
            "finca": SelectFinca(attrs={"class": "form-select"}),
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
            "finca": "Finca donde trabajas (punto de entrega)",
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
        self.fields["finca"].queryset = (
            Finca.objects.filter(activo=True, fondo__activo=True).select_related("fondo").order_by("orden", "nombre")
        )
        self.fields["finca"].required = False
        self.fields["finca"].empty_label = "Selecciona tu finca"
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

    def clean(self):
        datos = super().clean()
        fondo, finca = datos.get("fondo"), datos.get("finca")
        if fondo is None:
            return datos
        if finca is not None and finca.fondo_id != fondo.id:
            self.add_error("finca", "Esa finca no pertenece al fondo seleccionado.")
        elif finca is None and fondo.fincas.filter(activo=True).exists():
            self.add_error("finca", "Selecciona la finca donde trabajas para saber dónde entregar tu pedido.")
        return datos


class RespuestaFondoForm(forms.Form):
    """Decisión del gestor. No guarda nada: la vista delega en services.aplicar_decision."""

    vinculacion_validada = forms.TypedChoiceField(
        label="¿La persona trabaja/está afiliada con la entidad?",
        choices=(("", "Seleccione"), ("True", "Sí"), ("False", "No")),
        coerce=lambda v: v == "True",
        empty_value=None,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    estado = forms.ChoiceField(
        label="Decisión",
        choices=[("", "Seleccione")] + [
            c for c in SolicitudDescuentoNomina.ESTADOS
            if c[0] != SolicitudDescuentoNomina.ESTADO_PENDIENTE
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    cupo_disponible_reportado = forms.DecimalField(
        label="Cupo disponible",
        required=False,
        min_value=0,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
    )
    valor_aprobado = forms.DecimalField(
        label="Valor aprobado",
        required=False,
        min_value=0,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
    )
    referencia_fondo = forms.CharField(
        label="Referencia interna del fondo",
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    respuesta_fondo = forms.CharField(
        label="Observaciones del fondo",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
    )

    def __init__(self, *args, solicitud, **kwargs):
        self.solicitud = solicitud
        kwargs.setdefault("initial", {
            "vinculacion_validada": {True: "True", False: "False"}.get(solicitud.vinculacion_validada, ""),
            "cupo_disponible_reportado": solicitud.cupo_disponible_reportado,
            "referencia_fondo": solicitud.referencia_fondo,
        })
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        S = SolicitudDescuentoNomina
        vinculacion = cleaned.get("vinculacion_validada")
        estado = cleaned.get("estado")
        cupo = cleaned.get("cupo_disponible_reportado")
        aprobado = cleaned.get("valor_aprobado")
        solicitado = self.solicitud.valor_solicitado or Decimal("0")

        if vinculacion is None:
            self.add_error("vinculacion_validada", "Debe validar la vinculación del solicitante.")

        if vinculacion is False and estado and estado != S.ESTADO_RECHAZADA:
            self.add_error("estado", "Si la persona no está vinculada, la solicitud debe rechazarse.")

        # Aprobación total: el valor aprobado es siempre el solicitado exacto (con sus centavos).
        if estado == S.ESTADO_APROBADA:
            aprobado = cleaned["valor_aprobado"] = solicitado
            self.errors.pop("valor_aprobado", None)

        if estado in (S.ESTADO_APROBADA, S.ESTADO_APROBADA_PARCIAL):
            if cupo is None:
                self.add_error("cupo_disponible_reportado", "Informe el cupo disponible.")
            if aprobado is None or aprobado <= 0:
                self.add_error("valor_aprobado", "Informe un valor aprobado mayor a cero.")
            elif aprobado > solicitado:
                self.add_error("valor_aprobado", "El valor aprobado no puede superar el valor solicitado.")
            elif cupo is not None and aprobado > cupo:
                self.add_error("valor_aprobado", "El valor aprobado no puede superar el cupo reportado.")
            elif estado == S.ESTADO_APROBADA_PARCIAL and aprobado >= solicitado:
                self.add_error("valor_aprobado", "Para aprobación parcial, el valor debe ser menor al solicitado.")

        if estado == S.ESTADO_RECHAZADA:
            cleaned["valor_aprobado"] = Decimal("0")

        return cleaned


class CargaPadronForm(forms.Form):
    archivo = forms.FileField(
        label="Archivo CSV del padrón",
        help_text="Columnas: documento, cupo_disponible y opcionalmente nombre, empresa, activo.",
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".csv,text/csv"}),
    )
    desactivar_ausentes = forms.BooleanField(
        label="Desactivar afiliados que no estén en este archivo",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def clean_archivo(self):
        archivo = self.cleaned_data["archivo"]
        if archivo.size > 10 * 1024 * 1024:
            raise forms.ValidationError("El archivo no puede superar 10 MB.")
        if not archivo.name.lower().endswith(".csv"):
            raise forms.ValidationError("Cargue un archivo .csv.")
        return archivo
