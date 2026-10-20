import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.catalogos.models import Categoria, Marca, Presentacion, UnidadMedida
from apps.fondos.models import AfiliadoFondo, CorteNomina, FondoEmpleado, SolicitudDescuentoNomina
from apps.fondos.reportes import periodo_desde_texto
from apps.pedidos.models import Pedido
from apps.productos.models import Producto, ProductoPresentacion
from apps.promociones.models import Combo

S = SolicitudDescuentoNomina


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    WOMPI_PUBLIC_KEY="pub_test_x",
    WOMPI_INTEGRITY_SECRET="test_integrity_x",
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework.authentication.TokenAuthentication",
            "rest_framework.authentication.SessionAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
        "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
        "PAGE_SIZE": 24,
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    },
)
class ApiBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.cliente = User.objects.create_user(username="ana", password="clave-segura-1", email="ana@example.com")
        self.gestor = User.objects.create_user(username="gestor", password="clave-segura-2", email="g@example.com")
        self.otro_gestor = User.objects.create_user(username="otro", password="x")

        unidad = UnidadMedida.objects.create(nombre="Gramo", abreviatura="g")
        categoria = Categoria.objects.create(nombre="Lácteos", icono="cup-straw")
        marca = Marca.objects.create(nombre="Tío Campo")
        producto = Producto.objects.create(codigo="Q1", nombre="Queso campesino", categoria=categoria, marca=marca)
        self.presentacion = ProductoPresentacion.objects.create(
            producto=producto, codigo="Q1-500",
            presentacion=Presentacion.objects.create(nombre="500 g", cantidad=500, unidad=unidad),
            precio=Decimal("40000"),
        )
        self.combo = Combo.objects.create(codigo="C1", nombre="Combo", precio=Decimal("20000"), stock=2)

        self.fondo = FondoEmpleado.objects.create(
            nombre="Fondo API", nit="900123", correo="fondo@example.com",
            modo_verificacion=FondoEmpleado.MODO_PADRON, decision_automatica=True,
        )
        self.fondo.gestores.add(self.gestor)
        FondoEmpleado.objects.create(nombre="Otro fondo").gestores.add(self.otro_gestor)
        AfiliadoFondo.objects.create(fondo=self.fondo, documento="1020304050", cupo_disponible=Decimal("60000"))

        self.api = APIClient()

    def como(self, usuario):
        token, _ = Token.objects.get_or_create(user=usuario)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def llenar_carrito(self, cantidad=2):
        respuesta = self.api.post(
            reverse("api:carrito_items"), {"tipo": "p", "id": self.presentacion.id, "cantidad": cantidad}, format="json"
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return respuesta.json()

    def compra_nomina(self):
        """Cliente autenticado: carrito → pedido por nómina → solicitud (padrón aprueba parcial)."""
        self.como(self.cliente)
        self.llenar_carrito(2)                       # $80.000, cupo $60.000 → parcial
        pedido = self.api.post(reverse("api:pedidos"), {
            "metodo_pago": "NOMINA", "direccion_entrega": "Calle 1", "ciudad": "Bogotá",
        }, format="json").json()
        respuesta = self.api.post(reverse("api:solicitudes"), {
            "pedido": pedido["id"], "fondo": self.fondo.id, "nombre_completo": "Ana Pérez",
            "documento": "1.020.304.050", "empresa": "Tío Campo SAS", "autoriza_tratamiento": True,
        }, format="json")
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        return pedido, respuesta.json()


class CatalogoYCarritoApiTest(ApiBase):
    def test_catalogo_publico(self):
        datos = self.api.get(reverse("api:productos"), {"q": "queso"}).json()
        self.assertEqual(datos["count"], 1)
        producto = datos["results"][0]
        self.assertEqual(producto["presentaciones"][0]["precio"], "40000.00")
        self.assertEqual(self.api.get(reverse("api:categorias")).json()[0]["icono"], "cup-straw")
        self.assertEqual(self.api.get(reverse("api:combos")).json()["count"], 1)
        self.assertEqual(self.api.get(reverse("api:producto", args=[producto["id"]])).status_code, 200)

    def test_carrito_invitado(self):
        datos = self.llenar_carrito(3)
        self.assertEqual((datos["cantidad_total"], datos["total"]), (3, "120000.00"))
        datos = self.api.post(reverse("api:carrito_items"), {"tipo": "c", "id": self.combo.id, "cantidad": 9},
                              format="json").json()
        self.assertEqual(datos["cantidad"], 2)                 # limitado por stock
        self.assertIn("Solo hay 2", datos["mensaje"])
        self.assertEqual(self.api.delete(reverse("api:carrito")).json()["cantidad_total"], 0)

    def test_validaciones_carrito(self):
        self.assertEqual(self.api.post(reverse("api:carrito_items"), {"tipo": "x", "id": 1, "cantidad": 1},
                                       format="json").status_code, 400)
        self.assertEqual(self.api.post(reverse("api:carrito_items"), {"tipo": "p", "id": 9999, "cantidad": 1},
                                       format="json").status_code, 404)

    def test_documentacion(self):
        self.assertEqual(self.api.get(reverse("api_schema")).status_code, 200)
        self.assertEqual(self.api.get(reverse("api_docs")).status_code, 200)


class PedidosApiTest(ApiBase):
    def test_token(self):
        respuesta = self.api.post(reverse("api:token"), {"username": "ana", "password": "clave-segura-1"}, format="json")
        self.assertIn("token", respuesta.json())

    def test_invitado_compra_y_paga_en_linea(self):
        self.llenar_carrito(1)
        respuesta = self.api.post(reverse("api:pedidos"), {
            "metodo_pago": "ELECTRONICO", "direccion_entrega": "Calle 1", "ciudad": "Bogotá",
            "nombre": "Ana Pérez", "correo": "ana@example.com", "telefono": "3001234567",
            "autoriza_tratamiento": True,
        }, format="json")
        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        pedido = respuesta.json()
        self.assertTrue(pedido["pago_en_linea_disponible"])
        self.assertIn("codigo_acceso", pedido)

        pago = self.api.post(reverse("api:pedido_pago_en_linea", args=[pedido["id"]])).json()
        self.assertTrue(pago["url"].startswith("https://checkout.wompi.co/p/"))

        # Otro cliente sin la sesión no lo ve; con el código de seguimiento sí.
        otro = APIClient()
        self.assertEqual(otro.get(reverse("api:pedido", args=[pedido["id"]])).status_code, 404)
        self.assertEqual(
            otro.get(reverse("api:pedido_seguimiento", args=[pedido["codigo_acceso"]])).json()["numero"],
            pedido["numero"],
        )

    def test_invitado_sin_datos_y_nomina_sin_sesion(self):
        self.llenar_carrito(1)
        respuesta = self.api.post(reverse("api:pedidos"), {
            "metodo_pago": "OTRO", "direccion_entrega": "Calle 1", "ciudad": "Bogotá",
        }, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("correo", respuesta.json()["errores"])

        respuesta = self.api.post(reverse("api:pedidos"), {
            "metodo_pago": "NOMINA", "direccion_entrega": "Calle 1", "ciudad": "Bogotá",
        }, format="json")
        self.assertEqual(respuesta.status_code, 401)
        self.assertFalse(Pedido.objects.exists())

    def test_flujo_nomina_parcial_y_saldo(self):
        pedido, solicitud = self.compra_nomina()
        self.assertEqual(solicitud["estado"], S.ESTADO_APROBADA_PARCIAL)
        self.assertEqual(solicitud["valor_aprobado"], "60000.00")

        pedido = self.api.get(reverse("api:pedido", args=[pedido["id"]])).json()
        self.assertEqual((pedido["estado"], pedido["saldo_pendiente"]), ("APROBADO_PARCIAL", "20000.00"))
        self.assertTrue(pedido["requiere_definir_saldo"])

        pedido = self.api.post(reverse("api:pedido_pagar_saldo", args=[pedido["id"]]),
                               {"metodo_pago_saldo": "ELECTRONICO"}, format="json").json()
        self.assertEqual(pedido["estado"], "PENDIENTE_PAGO")
        self.assertEqual(len(self.api.get(reverse("api:pedidos")).json()), 1)
        self.assertEqual(len(self.api.get(reverse("api:solicitudes")).json()), 1)

    def test_solicitud_exige_autorizacion(self):
        self.como(self.cliente)
        self.llenar_carrito(1)
        pedido = self.api.post(reverse("api:pedidos"), {
            "metodo_pago": "NOMINA", "direccion_entrega": "Calle 1", "ciudad": "Bogotá",
        }, format="json").json()
        respuesta = self.api.post(reverse("api:solicitudes"), {
            "pedido": pedido["id"], "fondo": self.fondo.id, "nombre_completo": "Ana Pérez",
            "documento": "1020304050", "empresa": "Tío Campo", "autoriza_tratamiento": False,
        }, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("autoriza_tratamiento", respuesta.json()["errores"])

    def test_nomina_requiere_autenticacion(self):
        self.assertEqual(self.api.get(reverse("api:solicitudes")).status_code, 401)
        self.assertEqual(self.api.get(reverse("api:fondos")).status_code, 401)


class GestorApiTest(ApiBase):
    def test_permisos(self):
        self.como(self.cliente)
        self.assertEqual(self.api.get(reverse("api:gestor_solicitudes")).status_code, 403)
        _, solicitud = self.compra_nomina()
        self.como(self.otro_gestor)
        self.assertEqual(self.api.get(reverse("api:gestor_solicitudes")).json()["count"], 0)
        self.assertEqual(self.api.get(reverse("api:gestor_solicitud", args=[solicitud["id"]])).status_code, 404)

    def test_decision_manual(self):
        self.fondo.decision_automatica = False
        self.fondo.save()
        _, solicitud = self.compra_nomina()
        self.assertEqual(solicitud["estado"], S.ESTADO_PENDIENTE)

        self.como(self.gestor)
        detalle = self.api.get(reverse("api:gestor_solicitud", args=[solicitud["id"]])).json()
        self.assertEqual(detalle["documento"], "1.020.304.050")
        url = reverse("api:gestor_decision", args=[solicitud["id"]])
        malo = self.api.post(url, {"vinculacion_validada": True, "estado": "APROBADA",
                                   "cupo_disponible_reportado": "90000", "valor_aprobado": "50000"}, format="json")
        self.assertEqual(malo.status_code, 400)               # total debe ser igual al solicitado
        bueno = self.api.post(url, {"vinculacion_validada": True, "estado": "APROBADA_PARCIAL",
                                    "cupo_disponible_reportado": "60000", "valor_aprobado": "50000"}, format="json")
        self.assertEqual(bueno.json()["estado"], "APROBADA_PARCIAL")
        self.assertEqual(self.api.post(url, {"vinculacion_validada": False, "estado": "RECHAZADA"},
                                       format="json").status_code, 409)

    def test_fondos_con_fincas_y_solicitud_con_finca(self):
        from apps.fondos.models import Finca

        finca = Finca.objects.create(fondo=self.fondo, nombre="La Esperanza", municipio="Madrid")
        self.como(self.cliente)
        fondos = self.api.get(reverse("api:fondos")).json()
        self.assertEqual(fondos[0]["fincas"][0]["nombre"], "La Esperanza")

        self.llenar_carrito(1)
        pedido = self.api.post(reverse("api:pedidos"), {"metodo_pago": "NOMINA"}, format="json").json()
        sin_finca = self.api.post(reverse("api:solicitudes"), {
            "pedido": pedido["id"], "fondo": self.fondo.id, "nombre_completo": "Ana Pérez",
            "documento": "1020304050", "empresa": "Flores SAS", "autoriza_tratamiento": True,
        }, format="json")
        self.assertIn("finca", sin_finca.json()["errores"])
        con_finca = self.api.post(reverse("api:solicitudes"), {
            "pedido": pedido["id"], "fondo": self.fondo.id, "finca": finca.id, "nombre_completo": "Ana Pérez",
            "documento": "1020304050", "empresa": "Flores SAS", "autoriza_tratamiento": True,
        }, format="json")
        self.assertEqual(con_finca.json()["finca"]["nombre"], "La Esperanza")

    def test_padron_por_api(self):
        self.como(self.gestor)
        archivo = io.BytesIO(b"documento;cupo_disponible\n555;10000\n")
        archivo.name = "padron.csv"
        datos = self.api.post(reverse("api:gestor_padron", args=[self.fondo.id]), {"archivo": archivo},
                              format="multipart").json()
        self.assertEqual(datos["creados"], 1)


class ReporteNominaTest(ApiBase):
    """Archivo mensual para que el fondo aplique el descuento por nómina."""

    def aprobar_en(self, mes):
        _, solicitud = self.compra_nomina()
        fecha = timezone.make_aware(timezone.datetime(*map(int, mes.split("-")), 15, 10, 0))
        S.objects.filter(pk=solicitud["id"]).update(fecha_respuesta=fecha)
        return solicitud

    def test_reporte_csv_excel_y_corte(self):
        solicitud = self.aprobar_en("2026-09")
        self.como(self.gestor)
        url = reverse("api:gestor_reporte", args=[self.fondo.id])

        datos = self.api.get(url, {"mes": "2026-09"}).json()
        self.assertEqual((datos["cantidad"], datos["total"], datos["cerrado"]), (1, "60000.00", False))

        csv = self.api.get(url, {"mes": "2026-09", "formato": "csv"})
        texto = csv.content.decode("utf-8-sig")
        self.assertIn("Valor a descontar", texto)
        self.assertIn("1.020.304.050;Ana Pérez;Tío Campo SAS", texto)
        self.assertIn("60000,00", texto)
        self.assertIn("nomina_900123_2026-09.csv", csv["Content-Disposition"])

        excel = self.api.get(url, {"mes": "2026-09", "formato": "xlsx"})
        hoja = load_workbook(io.BytesIO(excel.content)).active
        self.assertEqual(hoja["K2"].value, 60000)                 # Valor a descontar
        self.assertEqual(hoja["E1"].value, "Finca / punto de entrega")
        self.assertEqual(hoja["B2"].value, "1.020.304.050")

        cerrar = reverse("api:gestor_cerrar_corte", args=[self.fondo.id])
        corte = self.api.post(cerrar, {"mes": "2026-09"}, format="json")
        self.assertEqual(corte.status_code, 201)
        self.assertEqual(self.api.post(cerrar, {"mes": "2026-09"}, format="json").status_code, 409)
        self.assertTrue(self.api.get(url, {"mes": "2026-09"}).json()["cerrado"])

        # Ya reportada: no vuelve a salir el mes siguiente.
        self.assertEqual(self.api.get(url, {"mes": "2026-10"}).json()["cantidad"], 0)
        self.assertEqual(S.objects.get(pk=solicitud["id"]).corte.periodo, periodo_desde_texto("2026-09"))

    def test_aprobacion_tardia_sale_en_el_siguiente_corte(self):
        self.aprobar_en("2026-09")
        self.como(self.gestor)
        self.api.post(reverse("api:gestor_cerrar_corte", args=[self.fondo.id]), {"mes": "2026-09"}, format="json")
        # Aprobada en septiembre pero después del cierre: va en octubre.
        AfiliadoFondo.objects.update(cupo_disponible=Decimal("60000"))
        self.aprobar_en("2026-09")
        self.como(self.gestor)
        datos = self.api.get(reverse("api:gestor_reporte", args=[self.fondo.id]), {"mes": "2026-10"}).json()
        self.assertEqual(datos["cantidad"], 1)

    def test_pedido_cancelado_no_se_reporta(self):
        self.aprobar_en("2026-09")
        Pedido.objects.update(estado=Pedido.ESTADO_CANCELADO)
        self.como(self.gestor)
        datos = self.api.get(reverse("api:gestor_reporte", args=[self.fondo.id]), {"mes": "2026-09"}).json()
        self.assertEqual(datos["cantidad"], 0)

    def test_portal_web_y_envio_por_correo(self):
        self.aprobar_en("2026-09")
        web = self.client
        web.force_login(self.gestor)
        url = reverse("fondos:gestion_reporte", args=[self.fondo.id])
        self.assertContains(web.get(url, {"mes": "2026-09"}), "Vista previa")
        self.assertEqual(web.get(url, {"mes": "2026-09", "formato": "xlsx"})["Content-Type"],
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        web.post(reverse("fondos:gestion_cerrar_corte", args=[self.fondo.id]), {"mes": "2026-09", "enviar": "1"})
        corte = CorteNomina.objects.get()
        self.assertIsNotNone(corte.enviado_en)
        enviado = [m for m in mail.outbox if "Descuentos por nómina" in m.subject][0]
        self.assertIn("fondo@example.com", enviado.to)
        self.assertTrue(enviado.attachments[0][0].endswith(".xlsx"))

        # Un gestor de otro fondo no puede ver ni cerrar el reporte.
        web.force_login(self.otro_gestor)
        self.assertEqual(web.get(url).status_code, 404)

    def test_comando_mensual(self):
        from django.core.management import call_command

        self.aprobar_en("2026-09")
        salida = io.StringIO()
        call_command("corte_nomina", mes="2026-09", cerrar=True, enviar=True, stdout=salida)
        self.assertIn("Corte cerrado", salida.getvalue())
        self.assertEqual(CorteNomina.objects.get().total, Decimal("60000"))
