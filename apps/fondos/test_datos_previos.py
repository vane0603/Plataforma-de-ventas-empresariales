from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.pedidos.models import Pedido

from .models import Finca, FondoEmpleado, SolicitudDescuentoNomina


class DatosPreviosSolicitudTest(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="maximino", password="x", email="maximino@example.com", first_name="Maximino",
        )
        self.fondo = FondoEmpleado.objects.create(nombre="Fondo Colsubsidio")
        self.finca = Finca.objects.create(fondo=self.fondo, nombre="Buquetero", municipio="Mosquera")
        self.client.force_login(self.usuario)

    def pedido(self, **extra):
        return Pedido.objects.create(
            usuario=self.usuario, metodo_pago=Pedido.METODO_NOMINA,
            estado=Pedido.ESTADO_PENDIENTE_SOLICITUD_NOMINA,
            subtotal=Decimal("6000"), total=Decimal("6000"),
            direccion_entrega="Finca", ciudad="Mosquera", **extra,
        )

    def anterior(self, **extra):
        datos = {
            "usuario": self.usuario, "fondo": self.fondo, "finca": self.finca, "pedido": self.pedido(),
            "nombre_completo": "Maximino Cervera", "documento": "1005820545", "telefono": "3104567890",
            "correo": "gestor.logistico@example.com", "empresa": "Flores SAS", "numero_afiliado": "A-77",
            "valor_solicitado": Decimal("6000"), "estado": SolicitudDescuentoNomina.ESTADO_APROBADA,
        }
        datos.update(extra)
        return SolicitudDescuentoNomina.objects.create(**datos)

    def inicial(self, pedido):
        respuesta = self.client.get(reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta, respuesta.context["form"].initial

    def test_primera_vez_usa_el_celular_del_checkout(self):
        respuesta, inicial = self.inicial(self.pedido(telefono_contacto="300 111 2233"))
        self.assertEqual(inicial["telefono"], "300 111 2233")
        self.assertEqual(inicial["correo"], "maximino@example.com")
        self.assertContains(respuesta, 'value="300 111 2233"')

    def test_reutiliza_los_datos_de_la_ultima_solicitud(self):
        self.anterior()
        respuesta, inicial = self.inicial(self.pedido())
        self.assertEqual(inicial["telefono"], "3104567890")
        self.assertEqual(inicial["documento"], "1005820545")
        self.assertEqual(inicial["empresa"], "Flores SAS")
        self.assertEqual(inicial["numero_afiliado"], "A-77")
        self.assertEqual((inicial["fondo"], inicial["finca"]), (self.fondo.id, self.finca.id))
        self.assertContains(respuesta, 'value="3104567890"')

    def test_el_celular_del_checkout_tiene_prioridad(self):
        self.anterior()
        _respuesta, inicial = self.inicial(self.pedido(telefono_contacto="3209998877"))
        self.assertEqual(inicial["telefono"], "3209998877")

    def test_no_usa_solicitudes_anonimizadas_ni_fincas_inactivas(self):
        self.anterior(anonimizada_en=timezone.now())
        _respuesta, inicial = self.inicial(self.pedido())
        self.assertNotIn("telefono", inicial)
        self.assertNotIn("documento", inicial)

        self.anterior()
        Finca.objects.filter(pk=self.finca.pk).update(activo=False)
        _respuesta, inicial = self.inicial(self.pedido())
        self.assertEqual(inicial["fondo"], self.fondo.id)
        self.assertNotIn("finca", inicial)

    def test_no_mezcla_datos_de_otro_usuario(self):
        otro = get_user_model().objects.create_user(username="otro", password="x")
        self.anterior(usuario=otro)
        _respuesta, inicial = self.inicial(self.pedido())
        self.assertNotIn("telefono", inicial)
        self.assertNotIn("documento", inicial)
