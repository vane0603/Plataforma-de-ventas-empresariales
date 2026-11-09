import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.catalogos.models import Categoria, Marca, Presentacion, UnidadMedida
from apps.pedidos.models import Pedido, PedidoItem
from apps.productos.models import Producto, ProductoPresentacion
from apps.promociones.models import Combo
from .models import ConfiguracionSiigo, FondoEmpleado, SolicitudDescuentoNomina
from .services import aplicar_decision

S = SolicitudDescuentoNomina


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BaseDescuento(TestCase):
    def setUp(self):
        User = get_user_model()
        self.empleado = User.objects.create_user(username="ana", password="x", email="ana@example.com")
        self.macs = FondoEmpleado.objects.create(nombre="MACS", descuento_empleados=Decimal("15"))
        self.sin_descuento = FondoEmpleado.objects.create(nombre="Fondo Flores")

        unidad = UnidadMedida.objects.create(nombre="Unidad", abreviatura="und")
        producto = Producto.objects.create(
            codigo="A1", nombre="Arepa rellena de queso",
            categoria=Categoria.objects.create(nombre="Panadería"), marca=Marca.objects.create(nombre="Tío Campo"),
        )
        self.arepa = ProductoPresentacion.objects.create(
            producto=producto, codigo="A1-80", precio=Decimal("7620"), codigo_siigo="702-15-45",
            presentacion=Presentacion.objects.create(nombre="*80GRS X 10 UNDS", cantidad=10, unidad=unidad),
        )
        self.combo = Combo.objects.create(codigo="C1", nombre="Combo desayuno", precio=Decimal("20000"), stock=5,
                                          codigo_siigo="800-1-1")
        self.client.force_login(self.empleado)

    def pedido(self, con_combo=False):
        lineas = [(self.arepa, None, Decimal("7620"))] + ([(None, self.combo, Decimal("20000"))] if con_combo else [])
        total = sum(valor for *_, valor in lineas)
        pedido = Pedido.objects.create(
            usuario=self.empleado, metodo_pago=Pedido.METODO_NOMINA, estado=Pedido.ESTADO_PENDIENTE_SOLICITUD_NOMINA,
            subtotal=total, total=total, direccion_entrega="Por definir", ciudad="",
        )
        for presentacion, combo, valor in lineas:
            PedidoItem.objects.create(
                pedido=pedido, producto_presentacion=presentacion, combo=combo,
                producto_nombre=presentacion.producto.nombre if presentacion else combo.nombre,
                referencia="R", presentacion=presentacion.presentacion.nombre if presentacion else "Combo",
                cantidad=1, precio_unitario=valor, subtotal=valor,
            )
        return pedido

    def solicitar(self, pedido, fondo):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]), {
                "fondo": fondo.id, "nombre_completo": "Pérez Gómez Ana", "documento": "1000000001",
                "empresa": "MACS", "autoriza_tratamiento": "on",
            })
        pedido.refresh_from_db()
        return S.objects.get(pedido=pedido)


class DescuentoEmpleadosTest(BaseDescuento):
    def test_la_pantalla_muestra_el_descuento_del_fondo(self):
        respuesta = self.client.get(reverse("fondos:solicitar_descuento_nomina", args=[self.pedido(con_combo=True).id]))
        self.assertContains(respuesta, f'"{self.macs.id}": {{"porcentaje": "15", "valor": 1143}}')
        self.assertNotContains(respuesta, f'"{self.sin_descuento.id}":')

    def test_15_por_ciento_en_productos_y_no_en_combos(self):
        pedido = self.pedido(con_combo=True)
        solicitud = self.solicitar(pedido, self.macs)
        self.assertEqual(pedido.subtotal, Decimal("27620"))
        self.assertEqual(pedido.descuento, Decimal("1143"))
        self.assertEqual(pedido.total, Decimal("26477"))
        self.assertEqual(solicitud.valor_solicitado, Decimal("26477"))
        descuentos = dict(pedido.items.values_list("producto_nombre", "descuento"))
        self.assertEqual(descuentos, {"Arepa rellena de queso": Decimal("1143"), "Combo desayuno": Decimal("0")})

        confirmacion = self.client.get(reverse("pedidos:confirmacion", args=[pedido.id]))
        self.assertContains(confirmacion, "Descuento empleados")

    def test_fondo_sin_descuento(self):
        pedido = self.pedido()
        self.solicitar(pedido, self.sin_descuento)
        self.assertEqual((pedido.descuento, pedido.total), (Decimal("0"), Decimal("7620")))

    def test_si_el_fondo_rechaza_se_quita_el_descuento(self):
        pedido = self.pedido()
        solicitud = self.solicitar(pedido, self.macs)
        aplicar_decision(solicitud, estado=S.ESTADO_RECHAZADA, valor_aprobado=0, vinculado=False, origen=S.ORIGEN_GESTOR)
        pedido.refresh_from_db()
        self.assertEqual((pedido.descuento, pedido.total), (Decimal("0"), Decimal("7620")))
        self.assertFalse(pedido.items.filter(descuento__gt=0).exists())

    def test_si_aprueba_conserva_el_descuento(self):
        pedido = self.pedido()
        solicitud = self.solicitar(pedido, self.macs)
        aplicar_decision(solicitud, estado=S.ESTADO_APROBADA, valor_aprobado=Decimal("6477"), vinculado=True,
                         origen=S.ORIGEN_GESTOR)
        pedido.refresh_from_db()
        self.assertEqual((pedido.total, pedido.valor_nomina, pedido.saldo_pendiente), (Decimal("6477"), Decimal("6477"), 0))

    def test_siigo_igual_a_la_factura_5584_del_ejemplo(self):
        """Arepa de 7.620 con 15 %: ingreso 7.620 (descuento 1.143), cartera 6.477, descuento 1.143."""
        ConfiguracionSiigo.objects.create(fondo=self.macs, siguiente_numero=5584)
        pedido = self.pedido()
        solicitud = self.solicitar(pedido, self.macs)
        aplicar_decision(solicitud, estado=S.ESTADO_APROBADA, valor_aprobado=Decimal("6477"), vinculado=True,
                         origen=S.ORIGEN_GESTOR)

        contador = get_user_model().objects.create_user(username="contador", password="x")
        contador.user_permissions.add(*Permission.objects.filter(codename__in=["view_pedido", "change_pedido"]))
        self.client.force_login(contador)
        respuesta = self.client.post(reverse("pedidos:siigo"), {
            "desde": "2000-01-01", "hasta": "2100-12-31", "numero_inicial": "5584", "pedidos": [pedido.pk],
        })
        hoja = load_workbook(io.BytesIO(respuesta.content)).active

        filas = [{c.column_letter: c.value for c in hoja[n]} for n in range(6, 11)]
        self.assertEqual(
            [(f["M"], f["D"], f["E"], f["F"], f["S"], f["Y"], f["L"]) for f in filas],
            [
                (1, 4135950400, "C", 7620, 0, 1143, 161),
                (2, 1365950100, "D", 6477, 0, 0, 0),
                (3, 4135980000, "D", 1143, 0, 0, 0),
                (4, 1435010400, "C", 0, 7620, 1143, 161),
                (5, 6135950400, "D", 0, 7620, 1143, 161),
            ],
        )
        descuento = filas[2]
        self.assertEqual(descuento["R"], "PÉREZ GÓMEZ ANA".ljust(50))
        self.assertEqual((descuento["V"], descuento["CV"], descuento["CW"], descuento["BS"], descuento["BV"]), (0, " " * 5, 0, "   ", 0))
        self.assertIsNone(hoja.cell(row=11, column=1).value)


class AprobacionTotalTest(BaseDescuento):
    """Al aprobar en total, el valor aprobado es el solicitado exacto (aunque tenga centavos)."""

    def test_aprobada_toma_el_valor_solicitado(self):
        ProductoPresentacion.objects.filter(pk=self.arepa.pk).update(precio=Decimal("7620.01"))
        pedido = self.pedido()
        PedidoItem.objects.filter(pedido=pedido).update(precio_unitario=Decimal("7620.01"), subtotal=Decimal("7620.01"))
        Pedido.objects.filter(pk=pedido.pk).update(subtotal=Decimal("7620.01"), total=Decimal("7620.01"))
        pedido.refresh_from_db()
        solicitud = self.solicitar(pedido, self.macs)
        self.assertEqual(solicitud.valor_solicitado, Decimal("6477.01"))

        gestor = get_user_model().objects.create_user(username="gestor", password="x")
        self.macs.gestores.add(gestor)
        self.client.force_login(gestor)
        url = reverse("fondos:gestion_detalle", args=[solicitud.id])
        pagina = self.client.get(url)
        self.assertContains(pagina, "Solicitado: $6.477,01")
        self.assertContains(pagina, 'const solicitado = "6477.01"')

        # Aunque el gestor deje vacío o escriba otro valor, se aprueba el solicitado exacto.
        respuesta = self.client.post(url, {
            "vinculacion_validada": "True", "estado": "APROBADA", "cupo_disponible_reportado": "700000",
            "valor_aprobado": "6477",
        })
        self.assertRedirects(respuesta, url)
        solicitud.refresh_from_db()
        pedido.refresh_from_db()
        self.assertEqual((solicitud.estado, solicitud.valor_aprobado), (S.ESTADO_APROBADA, Decimal("6477.01")))
        self.assertEqual(pedido.saldo_pendiente, 0)

    def test_aprobada_sin_cupo_suficiente_no_pasa(self):
        solicitud = self.solicitar(self.pedido(), self.macs)
        gestor = get_user_model().objects.create_user(username="gestor", password="x")
        self.macs.gestores.add(gestor)
        self.client.force_login(gestor)
        respuesta = self.client.post(reverse("fondos:gestion_detalle", args=[solicitud.id]), {
            "vinculacion_validada": "True", "estado": "APROBADA", "cupo_disponible_reportado": "1000",
        })
        self.assertContains(respuesta, "no puede superar el cupo")
