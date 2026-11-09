import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.carrito.models import Carrito, CarritoItem
from apps.promociones.models import Combo
from .entregas import despachar_pedidos
from .models import Pedido, PuntoRecogida


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", WHATSAPP_TOKEN="")
class RecogerEnTiendaTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.cliente = User.objects.create_user(username="ana", password="x", email="ana@example.com", first_name="Ana")
        self.repartidor = User.objects.create_user(username="repartidor", password="x")
        self.repartidor.groups.add(Group.objects.get(name="Repartidores"))
        self.tienda = PuntoRecogida.objects.create(
            nombre="Tienda Madrid", direccion="Calle 5 # 3-20", ciudad="Madrid, Cundinamarca",
            horario="Lunes a sábado de 8 a. m. a 6 p. m.",
        )
        combo = Combo.objects.create(codigo="C-1", nombre="Combo", precio=Decimal("20000"), stock=3)
        carrito = Carrito.objects.create(usuario=self.cliente, activo=True)
        CarritoItem.objects.create(carrito=carrito, combo=combo, cantidad=1, precio_unitario=combo.precio)
        self.client.force_login(self.cliente)

    def comprar(self, **datos):
        formulario = {"metodo_pago": Pedido.METODO_OTRO, "tipo_entrega": Pedido.TIPO_TIENDA}
        formulario.update(datos)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("pedidos:checkout"), formulario)

    def test_la_compra_muestra_la_opcion_solo_si_hay_puntos(self):
        self.assertContains(self.client.get(reverse("pedidos:checkout")), 'id="tc-tipo-entrega"')
        PuntoRecogida.objects.update(activo=False)
        self.assertNotContains(self.client.get(reverse("pedidos:checkout")), 'id="tc-tipo-entrega"')

    def test_recoger_en_tienda_sin_direccion(self):
        respuesta = self.comprar(punto_recogida=self.tienda.id)
        pedido = Pedido.objects.get()
        self.assertRedirects(respuesta, reverse("pedidos:confirmacion", args=[pedido.id]))
        self.assertEqual(pedido.tipo_entrega, Pedido.TIPO_TIENDA)
        self.assertEqual(pedido.punto_recogida, self.tienda)
        self.assertEqual(pedido.ciudad, "Madrid, Cundinamarca")
        self.assertIn("Calle 5 # 3-20", pedido.direccion_entrega)
        self.assertIn("Lo recoges en Tienda Madrid", mail.outbox[0].body)

        confirmacion = self.client.get(reverse("pedidos:confirmacion", args=[pedido.id]))
        self.assertContains(confirmacion, "Recoges tu pedido en Tienda Madrid")
        self.assertContains(confirmacion, "Lunes a sábado")

    def test_debe_elegir_el_punto(self):
        respuesta = self.comprar()
        self.assertContains(respuesta, "Selecciona dónde quieres recoger tu pedido.")
        self.assertFalse(Pedido.objects.exists())

    def test_con_nomina_no_se_recoge_en_tienda(self):
        self.comprar(metodo_pago=Pedido.METODO_NOMINA, punto_recogida=self.tienda.id)
        pedido = Pedido.objects.get()
        self.assertEqual(pedido.tipo_entrega, Pedido.TIPO_DOMICILIO)
        self.assertIsNone(pedido.punto_recogida)

    def test_domicilio_sigue_pidiendo_direccion(self):
        respuesta = self.comprar(tipo_entrega=Pedido.TIPO_DOMICILIO)
        self.assertContains(respuesta, "Escribe la dirección de entrega.")

    def test_al_despachar_se_avisa_que_esta_listo_para_recoger(self):
        self.comprar(punto_recogida=self.tienda.id)
        pedido = Pedido.objects.get()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            despachar_pedidos([pedido.id], usuario=self.repartidor)
        self.assertIn("listo para recoger", mail.outbox[0].subject)
        self.assertIn("$20.000", mail.outbox[0].body)  # se paga al recoger

        self.client.force_login(self.repartidor)
        lista = self.client.get(reverse("pedidos:entregas"))
        self.assertContains(lista, "Recoge en tienda")
        self.assertContains(lista, "Listo para recoger")

    def test_excel_de_entregas_con_los_filtros(self):
        self.comprar(punto_recogida=self.tienda.id)
        pedido = Pedido.objects.get()
        self.client.force_login(self.repartidor)
        lista = self.client.get(reverse("pedidos:entregas"), {"q": pedido.numero})
        self.assertContains(lista, "formato=xlsx")

        respuesta = self.client.get(reverse("pedidos:entregas"), {"q": pedido.numero, "formato": "xlsx"})
        self.assertIn("attachment", respuesta["Content-Disposition"])
        filas = list(load_workbook(io.BytesIO(respuesta.content))["Pedidos"].iter_rows(values_only=True))
        self.assertEqual(filas[1][0], pedido.numero)
        self.assertEqual(filas[1][4], "Recoger en tienda")

        vacio = self.client.get(reverse("pedidos:entregas"), {"q": "NO-EXISTE", "formato": "xlsx"})
        self.assertEqual(load_workbook(io.BytesIO(vacio.content))["Pedidos"].max_row, 1)

    def test_cliente_no_descarga_entregas(self):
        respuesta = self.client.get(reverse("pedidos:entregas"), {"formato": "xlsx"})
        self.assertEqual(respuesta.status_code, 403)
