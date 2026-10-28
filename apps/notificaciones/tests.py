import io
import json
import urllib.error
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.fondos.models import Finca, FondoEmpleado, SolicitudDescuentoNomina
from apps.fondos.services import aplicar_decision
from apps.pedidos.entregas import despachar_pedidos
from apps.pedidos.models import Pedido

from .canales.whatsapp import normalizar_celular
from .models import Notificacion
from .services import notificar, reenviar_fallidas

N = Notificacion
WHATSAPP = {"WHATSAPP_TOKEN": "token-prueba", "WHATSAPP_PHONE_NUMBER_ID": "1234567890"}


def respuesta_meta(datos):
    respuesta = mock.MagicMock()
    respuesta.read.return_value = json.dumps(datos).encode()
    respuesta.__enter__.return_value = respuesta
    return respuesta


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", WHATSAPP_TOKEN="")
class BaseNotificacionesTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.cliente = User.objects.create_user(
            username="ana", password="x", email="ana@example.com", first_name="Ana",
        )
        self.repartidor = User.objects.create_user(username="repartidor", password="x")
        self.repartidor.groups.add(Group.objects.get(name="Repartidores"))
        self.fondo = FondoEmpleado.objects.create(nombre="Fondo Flores")
        self.finca = Finca.objects.create(fondo=self.fondo, nombre="La Esperanza", municipio="Madrid")

    def pedido(self, metodo=Pedido.METODO_ELECTRONICO, estado=Pedido.ESTADO_PAGADO, **extra):
        datos = {
            "usuario": self.cliente, "metodo_pago": metodo, "estado": estado,
            "subtotal": Decimal("50000"), "total": Decimal("50000"),
            "direccion_entrega": "Calle 1", "ciudad": "Bogotá",
        }
        datos.update(extra)
        return Pedido.objects.create(**datos)

    def solicitud(self, pedido, estado=SolicitudDescuentoNomina.ESTADO_PENDIENTE, **extra):
        return SolicitudDescuentoNomina.objects.create(
            usuario=self.cliente, fondo=self.fondo, finca=self.finca, pedido=pedido,
            nombre_completo="Ana Pérez", documento="123", empresa="Flores SAS",
            valor_solicitado=pedido.total, estado=estado, **extra,
        )


class CorreoTest(BaseNotificacionesTest):
    def test_correo_en_html_y_texto_queda_registrado(self):
        pedido = self.pedido()
        notificar(N.EVENTO_PEDIDO_CREADO, pedido=pedido)

        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ["ana@example.com"])
        self.assertIn(str(pedido.codigo_acceso), correo.body)
        html, tipo = correo.alternatives[0]
        self.assertEqual(tipo, "text/html")
        self.assertIn("¡Recibimos tu pedido!", html)
        self.assertIn("$50.000", html)

        registro = N.objects.get()
        self.assertEqual((registro.estado, registro.canal, registro.intentos), (N.ESTADO_ENVIADA, N.CANAL_CORREO, 1))
        self.assertEqual(registro.destino, "ana@example.com")

    def test_el_destino_se_guarda_cifrado(self):
        notificar(N.EVENTO_PEDIDO_CREADO, pedido=self.pedido())
        with connection.cursor() as cursor:
            cursor.execute("SELECT destino FROM notificaciones_notificacion")
            crudo = cursor.fetchone()[0]
        self.assertNotIn("ana@example.com", crudo)

    def test_un_evento_no_se_repite(self):
        pedido = self.pedido()
        notificar(N.EVENTO_PAGO_APROBADO, pedido=pedido, extra={"monto": "50000", "referencia": "TC-1"})
        notificar(N.EVENTO_PAGO_APROBADO, pedido=pedido, extra={"monto": "50000", "referencia": "TC-1"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("TC-1", mail.outbox[0].body)

    def test_sin_correo_no_se_envia_nada(self):
        self.cliente.email = ""
        self.cliente.save()
        notificar(N.EVENTO_PEDIDO_CREADO, pedido=self.pedido())
        self.assertEqual((len(mail.outbox), N.objects.count()), (0, 0))

    def test_fallo_de_correo_no_rompe_y_se_reintenta(self):
        pedido = self.pedido()
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("SMTP caído")):
            notificar(N.EVENTO_PEDIDO_CREADO, pedido=pedido)
        fallida = N.objects.get()
        self.assertEqual(fallida.estado, N.ESTADO_FALLIDA)
        self.assertIn("SMTP caído", fallida.error)

        self.assertEqual(reenviar_fallidas(), (1, 0))
        fallida.refresh_from_db()
        self.assertEqual((fallida.estado, fallida.intentos), (N.ESTADO_ENVIADA, 2))
        self.assertEqual(len(mail.outbox), 1)

    def test_comando_no_reintenta_avisos_viejos(self):
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("caído")):
            notificar(N.EVENTO_PEDIDO_CREADO, pedido=self.pedido())
        N.objects.update(created_at=timezone.now() - timedelta(days=5))
        salida = io.StringIO()
        call_command("reenviar_notificaciones", stdout=salida)
        self.assertIn("Reenviadas: 0", salida.getvalue())

    def test_respuesta_parcial_del_fondo_indica_el_saldo(self):
        pedido = self.pedido(Pedido.METODO_NOMINA, Pedido.ESTADO_PENDIENTE_SOLICITUD_NOMINA)
        solicitud = self.solicitud(pedido)
        with self.captureOnCommitCallbacks(execute=True):
            aplicar_decision(
                solicitud, estado=SolicitudDescuentoNomina.ESTADO_APROBADA_PARCIAL,
                valor_aprobado=Decimal("30000"), vinculado=True,
                origen=SolicitudDescuentoNomina.ORIGEN_GESTOR,
            )
        registro = N.objects.get()
        self.assertEqual(registro.evento, N.EVENTO_NOMINA_PARCIAL)
        self.assertIn("Queda un saldo de $20.000", mail.outbox[0].body)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", **WHATSAPP)
class WhatsAppTest(BaseNotificacionesTest):
    def test_normalizar_celular(self):
        self.assertEqual(normalizar_celular("300 123 4567"), "573001234567")
        self.assertEqual(normalizar_celular("+57 (300) 123-4567"), "573001234567")
        self.assertEqual(normalizar_celular("573001234567"), "573001234567")
        self.assertEqual(normalizar_celular("601 123 4567"), "")
        self.assertEqual(normalizar_celular(""), "")

    @mock.patch("urllib.request.urlopen")
    def test_envia_plantilla_con_parametros(self, urlopen):
        urlopen.return_value = respuesta_meta({"messages": [{"id": "wamid.ABC"}]})
        pedido = self.pedido(avisos_whatsapp=True, telefono_contacto="300 123 4567")
        notificar(N.EVENTO_PEDIDO_DESPACHADO, pedido=pedido)

        peticion = urlopen.call_args.args[0]
        self.assertIn("/1234567890/messages", peticion.full_url)
        self.assertEqual(peticion.get_header("Authorization"), "Bearer token-prueba")
        cuerpo = json.loads(peticion.data)
        self.assertEqual(cuerpo["to"], "573001234567")
        self.assertEqual(cuerpo["template"]["name"], "tio_pedido_en_camino")
        parametros = [p["text"] for p in cuerpo["template"]["components"][0]["parameters"]]
        self.assertEqual(parametros, ["Ana", pedido.numero, "Calle 1, Bogotá"])

        whatsapp = N.objects.get(canal=N.CANAL_WHATSAPP)
        self.assertEqual((whatsapp.estado, whatsapp.id_externo), (N.ESTADO_ENVIADA, "wamid.ABC"))
        self.assertEqual(len(mail.outbox), 1)  # el correo sale igual

    @mock.patch("urllib.request.urlopen")
    def test_sin_autorizacion_no_se_escribe_por_whatsapp(self, urlopen):
        notificar(N.EVENTO_PEDIDO_CREADO, pedido=self.pedido(telefono_contacto="3001234567"))
        urlopen.assert_not_called()
        self.assertFalse(N.objects.filter(canal=N.CANAL_WHATSAPP).exists())

    @mock.patch("urllib.request.urlopen")
    def test_con_nomina_usa_el_celular_de_la_solicitud(self, urlopen):
        urlopen.return_value = respuesta_meta({"messages": [{"id": "wamid.X"}]})
        pedido = self.pedido(Pedido.METODO_NOMINA, Pedido.ESTADO_APROBADO_NOMINA, avisos_whatsapp=True)
        solicitud = self.solicitud(
            pedido, SolicitudDescuentoNomina.ESTADO_APROBADA,
            valor_aprobado=Decimal("50000"), telefono="310 555 0000",
        )
        notificar(N.EVENTO_NOMINA_APROBADA, solicitud=solicitud)
        cuerpo = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(cuerpo["to"], "573105550000")
        self.assertEqual(cuerpo["template"]["name"], "tio_nomina_aprobada")

    @mock.patch("urllib.request.urlopen")
    def test_error_de_meta_queda_registrado(self, urlopen):
        cuerpo_error = io.BytesIO(json.dumps({"error": {"message": "Template name does not exist"}}).encode())
        urlopen.side_effect = urllib.error.HTTPError("url", 404, "Not Found", {}, cuerpo_error)
        pedido = self.pedido(avisos_whatsapp=True, telefono_contacto="3001234567")
        notificar(N.EVENTO_PEDIDO_CREADO, pedido=pedido)
        fallida = N.objects.get(canal=N.CANAL_WHATSAPP)
        self.assertEqual(fallida.estado, N.ESTADO_FALLIDA)
        self.assertIn("Template name does not exist", fallida.error)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", WHATSAPP_TOKEN="")
class DespachoTest(BaseNotificacionesTest):
    def test_despachar_avisa_y_no_repite(self):
        listo = self.pedido()
        sin_pagar = self.pedido(Pedido.METODO_ELECTRONICO, Pedido.ESTADO_PENDIENTE_PAGO)
        with self.captureOnCommitCallbacks(execute=True):
            despachados = despachar_pedidos([listo.pk, sin_pagar.pk], usuario=self.repartidor)
        self.assertEqual(despachados, [listo])

        listo.refresh_from_db()
        self.assertIsNotNone(listo.despachado_en)
        self.assertEqual(listo.despachado_por, self.repartidor)
        self.assertTrue(listo.en_camino)
        self.assertEqual([m.subject for m in mail.outbox], [f"Tu pedido {listo.numero} va en camino"])

        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(despachar_pedidos([listo.pk]), [])
        self.assertEqual(len(mail.outbox), 1)

    def test_pedido_despachado_ya_no_se_puede_cancelar(self):
        pedido = self.pedido(Pedido.METODO_OTRO, Pedido.ESTADO_PENDIENTE_PAGO)
        self.assertTrue(pedido.puede_cancelarse)
        despachar_pedidos([pedido.pk])
        pedido.refresh_from_db()
        self.assertFalse(pedido.puede_cancelarse)

    def test_vista_despachar_varios_y_permisos(self):
        uno, dos = self.pedido(), self.pedido()
        url = reverse("pedidos:entregas_despachar")

        self.client.force_login(self.cliente)
        self.assertEqual(self.client.post(url, {"pedidos": [uno.pk]}).status_code, 403)

        self.client.force_login(self.repartidor)
        self.assertEqual(self.client.get(url).status_code, 405)
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(url, {"pedidos": [uno.pk, dos.pk], "volver": "https://otro-sitio.com/"})
        self.assertRedirects(respuesta, reverse("pedidos:entregas"))
        self.assertEqual(Pedido.objects.filter(despachado_en__isnull=False).count(), 2)
        self.assertEqual(len(mail.outbox), 2)

        lista = self.client.get(reverse("pedidos:entregas") + "?despacho=en_camino")
        self.assertContains(lista, "En camino")
        self.assertContains(lista, uno.numero)

    def test_cliente_ve_que_su_pedido_va_en_camino(self):
        pedido = self.pedido()
        despachar_pedidos([pedido.pk])
        self.client.force_login(self.cliente)
        self.assertContains(self.client.get(reverse("pedidos:confirmacion", args=[pedido.pk])), "Tu pedido va en camino")

    def test_anonimizar_borra_el_destino(self):
        pedido = self.pedido()
        notificar(N.EVENTO_PEDIDO_CREADO, pedido=pedido)
        Pedido.objects.filter(pk=pedido.pk).update(created_at=timezone.now() - timedelta(days=4000))
        call_command("anonimizar_datos", "--dias", "30", stdout=io.StringIO())
        self.assertEqual(N.objects.get().destino, "")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CheckoutWhatsAppTest(BaseNotificacionesTest):
    def setUp(self):
        from apps.carrito.models import Carrito, CarritoItem
        from apps.promociones.models import Combo

        super().setUp()
        combo = Combo.objects.create(codigo="C-1", nombre="Combo", precio=Decimal("20000"), stock=3)
        carrito = Carrito.objects.create(usuario=self.cliente, activo=True)
        CarritoItem.objects.create(carrito=carrito, combo=combo, cantidad=1, precio_unitario=combo.precio)
        self.client.force_login(self.cliente)

    def comprar(self, **datos):
        formulario = {
            "metodo_pago": Pedido.METODO_ELECTRONICO, "direccion_entrega": "Calle 1", "ciudad": "Bogotá",
            "telefono": "3001234567", "avisos_whatsapp": "on",
        }
        formulario.update(datos)
        return self.client.post(reverse("pedidos:checkout"), formulario)

    @override_settings(WHATSAPP_TOKEN="")
    def test_sin_whatsapp_activo_no_se_guarda_la_autorizacion(self):
        self.assertNotContains(self.client.get(reverse("pedidos:checkout")), "avisos_whatsapp")
        self.comprar()
        self.assertFalse(Pedido.objects.get().avisos_whatsapp)

    @override_settings(**WHATSAPP)
    @mock.patch("urllib.request.urlopen")
    def test_con_whatsapp_activo_se_guarda_la_autorizacion(self, urlopen):
        urlopen.return_value = respuesta_meta({"messages": [{"id": "wamid.1"}]})
        self.assertContains(self.client.get(reverse("pedidos:checkout")), 'name="avisos_whatsapp"')
        with self.captureOnCommitCallbacks(execute=True):
            self.comprar()
        pedido = Pedido.objects.get()
        self.assertTrue(pedido.avisos_whatsapp)
        self.assertEqual(json.loads(urlopen.call_args.args[0].data)["template"]["name"], "tio_pedido_recibido")
