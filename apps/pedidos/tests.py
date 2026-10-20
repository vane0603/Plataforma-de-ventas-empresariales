from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.carrito.models import Carrito, CarritoItem
from apps.promociones.models import Combo
from .models import Pedido


class StockCombosTest(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="comprador", password="x")
        self.combo = Combo.objects.create(codigo="C-1", nombre="Combo", precio=Decimal("20000"), stock=3)
        self.client.force_login(self.usuario)

    def comprar(self, cantidad, metodo=Pedido.METODO_OTRO):
        carrito, _ = Carrito.objects.get_or_create(usuario=self.usuario, activo=True)
        CarritoItem.objects.create(
            carrito=carrito, combo=self.combo, cantidad=cantidad, precio_unitario=self.combo.precio
        )
        return self.client.post(
            reverse("pedidos:checkout"),
            {"direccion_entrega": "Calle 1", "ciudad": "Bogotá", "metodo_pago": metodo},
        )

    def test_checkout_descuenta_stock_y_cancelar_lo_devuelve(self):
        self.comprar(2)
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.stock, 1)

        pedido = Pedido.objects.get(usuario=self.usuario)
        self.assertEqual(pedido.items.get().producto_nombre, "Combo")
        self.client.post(reverse("pedidos:cancelar", args=[pedido.id]))
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.stock, 3)

    def test_no_permite_sobreventa(self):
        self.comprar(2)
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.stock, 1)
        self.comprar(2)
        self.assertEqual(Pedido.objects.count(), 1)
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.stock, 1)

    def test_metodo_invalido(self):
        self.comprar(1, metodo="BITCOIN")
        self.assertFalse(Pedido.objects.exists())


class RegistroTest(TestCase):
    def test_registro_inicia_sesion(self):
        respuesta = self.client.post(
            reverse("registro"),
            {
                "username": "nuevo",
                "first_name": "Ana",
                "last_name": "Pérez",
                "email": "ana@example.com",
                "password1": "UnaClaveSegura#2026",
                "password2": "UnaClaveSegura#2026",
                "autoriza_tratamiento": "on",
            },
        )
        self.assertRedirects(respuesta, reverse("dashboard"))
        self.assertTrue(get_user_model().objects.filter(username="nuevo").exists())


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    WOMPI_PUBLIC_KEY="pub_test_x",
    WOMPI_INTEGRITY_SECRET="test_integrity_x",
)
class CompraInvitadoTest(TestCase):
    """Sin cuenta se puede comprar; solo el descuento por nómina exige iniciar sesión."""

    def setUp(self):
        self.combo = Combo.objects.create(codigo="C-9", nombre="Combo campo", precio=Decimal("25000"), stock=5)
        self.client.post(reverse("carrito:api_cantidad", args=["c", self.combo.id]), {"cantidad": 2})

    def datos(self, **extra):
        datos = {
            "nombre": "Ana Pérez",
            "correo": "ana@example.com",
            "telefono": "300 123 4567",
            "autoriza_tratamiento": "on",
            "direccion_entrega": "Calle 10 # 5-20",
            "ciudad": "Bogotá",
            "metodo_pago": Pedido.METODO_ELECTRONICO,
        }
        datos.update(extra)
        return datos

    def test_checkout_abre_sin_iniciar_sesion(self):
        respuesta = self.client.get(reverse("pedidos:checkout"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "La fecha de entrega se acuerda con el fondo de empleados")

    def test_invitado_compra_y_ve_su_pedido(self):
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(reverse("pedidos:checkout"), self.datos())
        pedido = Pedido.objects.get()
        self.assertRedirects(respuesta, reverse("pedidos:confirmacion", args=[pedido.id]))
        self.assertIsNone(pedido.usuario)
        self.assertEqual(
            (pedido.nombre_contacto, pedido.correo_contacto, pedido.telefono_contacto),
            ("Ana Pérez", "ana@example.com", "300 123 4567"),
        )
        self.assertEqual(pedido.total, Decimal("50000"))

        respuesta = self.client.get(reverse("pedidos:confirmacion", args=[pedido.id]))
        self.assertContains(respuesta, pedido.numero)
        self.assertContains(respuesta, "en línea")      # botón de pago Wompi

        # Correo de confirmación con enlace de seguimiento.
        self.assertEqual(mail.outbox[0].to, ["ana@example.com"])
        self.assertIn(str(pedido.codigo_acceso), mail.outbox[0].body)

        # El invitado puede iniciar el pago en línea.
        respuesta = self.client.post(reverse("pagos:pagar", args=[pedido.id]))
        self.assertTrue(respuesta["Location"].startswith("https://checkout.wompi.co/p/"))

    def test_invitado_debe_dar_sus_datos(self):
        respuesta = self.client.post(reverse("pedidos:checkout"), self.datos(nombre="", correo="", telefono=""))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Escribe tu correo")
        self.assertFalse(Pedido.objects.exists())

    def test_nomina_pide_iniciar_sesion_y_conserva_datos(self):
        respuesta = self.client.post(
            reverse("pedidos:checkout"),
            self.datos(nombre="", correo="", telefono="", metodo_pago=Pedido.METODO_NOMINA),
        )
        self.assertRedirects(
            respuesta,
            reverse("login") + "?next=" + reverse("pedidos:checkout").replace("/", "%2F"),
            fetch_redirect_response=False,
        )
        self.assertFalse(Pedido.objects.exists())

        usuario = get_user_model().objects.create_user(username="ana", password="x", email="ana@example.com")
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("pedidos:checkout"))
        self.assertContains(respuesta, "Calle 10 # 5-20")          # dirección conservada
        self.assertContains(respuesta, 'value="NOMINA" checked')    # método conservado
        self.assertContains(respuesta, "Combo campo")               # carrito conservado

        respuesta = self.client.post(
            reverse("pedidos:checkout"), self.datos(nombre="", correo="", metodo_pago=Pedido.METODO_NOMINA)
        )
        pedido = Pedido.objects.get()
        self.assertEqual(pedido.usuario, usuario)
        self.assertRedirects(respuesta, reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]))

    def test_otro_navegador_no_ve_el_pedido_salvo_con_el_enlace(self):
        self.client.post(reverse("pedidos:checkout"), self.datos())
        pedido = Pedido.objects.get()

        otro = Client()
        self.assertEqual(otro.get(reverse("pedidos:confirmacion", args=[pedido.id])).status_code, 404)
        self.assertEqual(otro.post(reverse("pedidos:cancelar", args=[pedido.id])).status_code, 404)

        respuesta = otro.get(reverse("pedidos:seguimiento", args=[pedido.codigo_acceso]))
        self.assertRedirects(respuesta, reverse("pedidos:confirmacion", args=[pedido.id]))
        self.assertEqual(otro.get(reverse("pedidos:confirmacion", args=[pedido.id])).status_code, 200)

    def test_invitado_puede_cancelar_y_se_devuelve_stock(self):
        self.client.post(reverse("pedidos:checkout"), self.datos(metodo_pago=Pedido.METODO_OTRO))
        pedido = Pedido.objects.get()
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.stock, 3)
        self.client.post(reverse("pedidos:cancelar", args=[pedido.id]))
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.stock, 5)

    def test_usuario_no_ve_pedidos_de_invitados_ajenos(self):
        self.client.post(reverse("pedidos:checkout"), self.datos())
        pedido = Pedido.objects.get()
        intruso = Client()
        intruso.force_login(get_user_model().objects.create_user(username="otro", password="x"))
        self.assertEqual(intruso.get(reverse("pedidos:confirmacion", args=[pedido.id])).status_code, 404)
