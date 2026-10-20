from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.pedidos.models import Pedido
from apps.promociones.models import Combo

from .models import AutorizacionDatos


class AutorizacionDatosTest(TestCase):
    """Ley 1581: sin autorización no se crea cuenta ni compra un invitado, y queda la prueba."""

    REGISTRO = {
        "username": "nuevo", "first_name": "Ana", "last_name": "Pérez", "email": "ana@example.com",
        "password1": "UnaClaveSegura#2026", "password2": "UnaClaveSegura#2026",
    }

    def setUp(self):
        self.combo = Combo.objects.create(codigo="C-1", nombre="Combo", precio=Decimal("10000"), stock=5)

    def checkout_invitado(self, cliente, **extra):
        cliente.post(reverse("carrito:api_cantidad", args=["c", self.combo.id]), {"cantidad": 1})
        datos = {
            "nombre": "Ana Pérez", "correo": "ana@example.com", "telefono": "3001234567",
            "direccion_entrega": "Calle 1", "ciudad": "Bogotá", "metodo_pago": Pedido.METODO_OTRO,
        }
        datos.update(extra)
        return cliente.post(reverse("pedidos:checkout"), datos)

    def test_registro_exige_y_guarda_la_autorizacion(self):
        respuesta = self.client.post(reverse("registro"), self.REGISTRO)
        self.assertContains(respuesta, "Debes autorizar el tratamiento")
        self.assertFalse(get_user_model().objects.exists())

        self.client.post(reverse("registro"), {**self.REGISTRO, "autoriza_tratamiento": "on"})
        usuario = get_user_model().objects.get(username="nuevo")
        autorizacion = AutorizacionDatos.objects.get()
        self.assertEqual(
            (autorizacion.usuario, autorizacion.origen, autorizacion.version_politica),
            (usuario, AutorizacionDatos.ORIGEN_REGISTRO, settings.POLITICA_DATOS_VERSION),
        )

    def test_registro_muestra_la_politica(self):
        self.assertContains(self.client.get(reverse("registro")), reverse("politica_datos"))

    def test_invitado_exige_y_guarda_la_autorizacion(self):
        respuesta = self.checkout_invitado(self.client)
        self.assertContains(respuesta, "Debes autorizar el tratamiento")
        self.assertFalse(Pedido.objects.exists())

        self.checkout_invitado(self.client, autoriza_tratamiento="on")
        pedido = Pedido.objects.get()
        autorizacion = AutorizacionDatos.objects.get()
        self.assertEqual((autorizacion.pedido, autorizacion.origen), (pedido, AutorizacionDatos.ORIGEN_CHECKOUT))

    def test_usuario_con_cuenta_no_vuelve_a_autorizar(self):
        usuario = get_user_model().objects.create_user(username="ana", password="x", email="ana@example.com")
        self.client.force_login(usuario)
        self.client.post(reverse("carrito:api_cantidad", args=["c", self.combo.id]), {"cantidad": 1})
        self.assertNotContains(self.client.get(reverse("pedidos:checkout")), "data-autorizacion")
        self.client.post(reverse("pedidos:checkout"), {
            "direccion_entrega": "Calle 1", "ciudad": "Bogotá", "metodo_pago": Pedido.METODO_OTRO,
        })
        self.assertEqual(Pedido.objects.get().usuario, usuario)
        self.assertFalse(AutorizacionDatos.objects.exists())

    def test_api_invitado_exige_la_autorizacion(self):
        api = APIClient()
        api.post(reverse("api:carrito_items"), {"tipo": "c", "id": self.combo.id, "cantidad": 1}, format="json")
        datos = {
            "metodo_pago": "OTRO", "direccion_entrega": "Calle 1", "ciudad": "Bogotá",
            "nombre": "Ana Pérez", "correo": "ana@example.com", "telefono": "3001234567",
        }
        respuesta = api.post(reverse("api:pedidos"), datos, format="json")
        self.assertIn("autoriza_tratamiento", respuesta.json()["errores"])
        respuesta = api.post(reverse("api:pedidos"), {**datos, "autoriza_tratamiento": True}, format="json")
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(AutorizacionDatos.objects.get().origen, AutorizacionDatos.ORIGEN_CHECKOUT)
