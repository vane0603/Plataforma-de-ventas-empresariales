import re

from django import forms

from .models import Pedido


class CheckoutForm(forms.Form):
    """
    Datos del checkout. Los datos de contacto son obligatorios para invitados;
    para usuarios con sesión se completan con los de su cuenta.
    """

    nombre = forms.CharField(label="Nombre completo", max_length=150, required=False)
    correo = forms.EmailField(label="Correo electrónico", required=False)
    telefono = forms.CharField(label="Celular", max_length=30, required=False)
    # No se piden con descuento por nómina: se entrega en la finca que elija el comprador.
    direccion_entrega = forms.CharField(label="Dirección de entrega", max_length=250, required=False)
    ciudad = forms.CharField(label="Ciudad", max_length=120, initial="Bogotá", required=False)
    observaciones = forms.CharField(label="Observaciones", required=False, widget=forms.Textarea)
    # Obligatoria para invitados (los usuarios autorizaron al crear su cuenta).
    autoriza_tratamiento = forms.BooleanField(label="Autorizo el tratamiento de mis datos", required=False)
    metodo_pago = forms.ChoiceField(
        label="Medio de pago",
        choices=Pedido.METODOS_PAGO,
        error_messages={"required": "Selecciona un medio de pago.", "invalid_choice": "Selecciona un medio de pago válido."},
    )

    def __init__(self, *args, usuario=None, **kwargs):
        self.usuario = usuario if usuario and usuario.is_authenticated else None
        super().__init__(*args, **kwargs)

    @property
    def requiere_login(self):
        """El descuento por nómina necesita una cuenta (el fondo verifica al titular)."""
        return self.usuario is None and self.cleaned_data.get("metodo_pago") == Pedido.METODO_NOMINA

    def clean_nombre(self):
        return " ".join(self.cleaned_data["nombre"].split())

    def clean_telefono(self):
        telefono = self.cleaned_data["telefono"].strip()
        if telefono and not re.fullmatch(r"\+?[0-9 ()-]{7,20}", telefono):
            raise forms.ValidationError("Escribe un número de celular válido.")
        return telefono

    def clean(self):
        datos = super().clean()
        if datos.get("metodo_pago") and datos.get("metodo_pago") != Pedido.METODO_NOMINA:
            if not datos.get("direccion_entrega", "").strip():
                self.add_error("direccion_entrega", "Escribe la dirección de entrega.")
            if not datos.get("ciudad", "").strip():
                self.add_error("ciudad", "Escribe la ciudad de entrega.")
        if self.usuario is None and datos.get("metodo_pago") != Pedido.METODO_NOMINA:
            if len(datos.get("nombre", "")) < 3:
                self.add_error("nombre", "Escribe tu nombre completo.")
            if not datos.get("correo"):
                self.add_error("correo", "Escribe tu correo para enviarte la confirmación.")
            if not datos.get("telefono"):
                self.add_error("telefono", "Escribe tu celular para contactarte.")
            if not datos.get("autoriza_tratamiento"):
                self.add_error("autoriza_tratamiento", "Debes autorizar el tratamiento de tus datos para continuar.")
        return datos

    def datos_contacto(self):
        datos = self.cleaned_data
        if self.usuario is not None:
            return {
                "nombre": datos["nombre"] or self.usuario.get_full_name() or self.usuario.username,
                "correo": datos["correo"] or self.usuario.email,
                "telefono": datos["telefono"],
            }
        return {"nombre": datos["nombre"], "correo": datos["correo"], "telefono": datos["telefono"]}
