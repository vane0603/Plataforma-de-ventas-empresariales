import io
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.catalogos.models import Categoria, Marca, Presentacion, UnidadMedida
from apps.fondos.models import ConfiguracionSiigo, FondoEmpleado, SolicitudDescuentoNomina
from apps.productos.models import Producto, ProductoPresentacion
from .models import Pedido, PedidoItem

S = SolicitudDescuentoNomina


def fila(hoja, numero):
    """Fila como dict columna -> valor."""
    return {celda.column_letter: celda.value for celda in hoja[numero]}


class ExportarSiigoTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.contador = User.objects.create_user(username="contador", password="x")
        self.contador.user_permissions.add(*Permission.objects.filter(codename__in=["view_pedido", "change_pedido"]))
        self.cliente = User.objects.create_user(username="ana", password="x")

        self.macs = FondoEmpleado.objects.create(nombre="MACS")
        self.config = ConfiguracionSiigo.objects.create(fondo=self.macs, siguiente_numero=5584)
        self.otro_fondo = FondoEmpleado.objects.create(nombre="Fondo Flores")

        unidad = UnidadMedida.objects.create(nombre="Gramo", abreviatura="g")
        producto = Producto.objects.create(
            codigo="A1", nombre="Arepa rellena de queso",
            categoria=Categoria.objects.create(nombre="Panadería"), marca=Marca.objects.create(nombre="Tío Campo"),
        )
        self.arepa = ProductoPresentacion.objects.create(
            producto=producto, codigo="A1-80", precio=Decimal("7620"), codigo_siigo="702-15-45",
            presentacion=Presentacion.objects.create(nombre="*80GRS X 10 UNDS", cantidad=80, unidad=unidad),
        )
        self.cafe = ProductoPresentacion.objects.create(
            producto=Producto.objects.create(codigo="C1", nombre="Café grano", categoria=producto.categoria, marca=producto.marca),
            codigo="C1-500", precio=Decimal("20000"), codigo_siigo="700-107-16", bodega_siigo=3,
            presentacion=Presentacion.objects.create(nombre="500 g", cantidad=500, unidad=unidad),
        )

        self.pedido1 = self.pedido(self.macs, "1000000001", "Pérez Gómez Ana María", datetime(2026, 11, 3, 7, 55, 37),
                                   [(self.arepa, 1)])
        self.pedido2 = self.pedido(self.macs, "80.000.002", "Rojas Díaz Carlos", datetime(2026, 11, 3, 11, 10, 57),
                                   [(self.cafe, 12), (self.arepa, 2)])
        self.de_otro_fondo = self.pedido(self.otro_fondo, "123", "Otra Persona", datetime(2026, 11, 3, 9, 0), [(self.arepa, 1)])
        self.client.force_login(self.contador)

    def pedido(self, fondo, documento, nombre, aprobado, lineas):
        total = sum(p.precio * cantidad for p, cantidad in lineas)
        pedido = Pedido.objects.create(
            usuario=self.cliente, metodo_pago=Pedido.METODO_NOMINA, estado=Pedido.ESTADO_APROBADO_NOMINA,
            subtotal=total, total=total, valor_nomina=total, direccion_entrega="Finca", ciudad="Madrid",
        )
        for presentacion, cantidad in lineas:
            PedidoItem.objects.create(
                pedido=pedido, producto_presentacion=presentacion, producto_nombre=presentacion.producto.nombre,
                referencia=presentacion.codigo, presentacion=presentacion.presentacion.nombre, cantidad=cantidad,
                precio_unitario=presentacion.precio, subtotal=presentacion.precio * cantidad,
            )
        S.objects.create(
            usuario=self.cliente, fondo=fondo, pedido=pedido, nombre_completo=nombre, documento=documento,
            empresa="MACS", valor_solicitado=total, valor_aprobado=total, estado=S.ESTADO_APROBADA,
            fecha_respuesta=timezone.make_aware(aprobado),
        )
        return pedido

    def generar(self, pedidos=None, **datos):
        """Descarga los pedidos marcados (por defecto los dos de MACS) desde el número inicial."""
        pedidos = pedidos if pedidos is not None else [self.pedido1, self.pedido2]
        datos = {"fondo": self.config.pk, "desde": "2026-11-01", "hasta": "2026-11-30",
                 "numero_inicial": "5584", "pedidos": [p.pk for p in pedidos], **datos}
        return self.client.post(reverse("pedidos:siigo"), datos)

    def test_vista_previa_solo_del_fondo_con_siigo(self):
        respuesta = self.client.get(reverse("pedidos:siigo"), {"desde": "2026-11-01", "hasta": "2026-11-30"})
        self.assertContains(respuesta, self.pedido1.numero)
        self.assertContains(respuesta, self.pedido2.numero)
        self.assertNotContains(respuesta, self.de_otro_fondo.numero)
        self.assertContains(respuesta, 'value="5584"')

    def test_archivo_con_el_formato_del_modelo_de_siigo(self):
        respuesta = self.generar()
        self.assertIn("siigo_macs_20261101_20261130.xlsx", respuesta["Content-Disposition"])
        hoja = load_workbook(io.BytesIO(respuesta.content)).active

        self.assertEqual(hoja["A1"].value, "*MACS COMERCIALIZADORA Y DISTRIBUIDORA S.A.S*")
        self.assertEqual(hoja["A3"].value, "De :  NOV  1/2026   A :  NOV 30/2026")
        self.assertEqual(hoja["A5"].value, "TIPO DE COMPROBANTE (OBLIGATORIO)")
        self.assertEqual(hoja["DY5"].value, "NÚMERO DEL INMUEBLE")
        self.assertEqual(hoja.max_column, 129)

        # Pedido 1 (un producto): ingreso, cartera, inventario y costo, como en el ejemplo.
        ingreso, cartera, inventario, costo = (fila(hoja, n) for n in range(6, 10))
        self.assertEqual([ingreso[c] for c in "ABCDEFGHIJKLM"], ["F", 3, 5584, 4135950400, "C", 7620, 2026, 11, 3, 500, 666, 161, 1])
        self.assertEqual(ingreso["P"], 1000000001)
        self.assertEqual(ingreso["R"], "AREPA RELLENA DE QUESO *80GRS X 10 UNDS".ljust(50))
        self.assertEqual([ingreso[c] for c in ("BS", "BT", "BU", "BV", "BX")], [702, 15, 45, 1, 1])
        self.assertEqual((ingreso["AL"], ingreso["AM"]), (20261103, 75537))

        self.assertEqual([cartera[c] for c in "DEFLM"], [1365950100, "D", 7620, 0, 2])
        self.assertEqual(cartera["R"], "PÉREZ GÓMEZ ANA MARÍA".ljust(50))
        self.assertEqual([cartera[c] for c in ("V", "CV", "CW", "CX", "CY", "CZ", "DA")], [3, "F-003", 5584, 1, 2026, 11, 3])
        self.assertEqual((cartera["BS"], cartera["BU"], cartera["BV"]), ("   ", "      ", 0))

        self.assertEqual([inventario[c] for c in ("D", "E", "F", "S", "BO", "CQ", "M")], [1435010400, "C", 0, 7620, "N", " ", 3])
        self.assertEqual([costo[c] for c in ("D", "E", "F", "S", "BO", "CQ", "M")], [6135950400, "D", 0, 7620, "N", 0, 4])
        self.assertEqual(costo["DG"], " " * 3000)

        # Pedido 2 (dos productos): 2 ingresos, cartera, 2 x (inventario, costo) = 7 filas, factura 5585.
        filas = [fila(hoja, n) for n in range(10, 17)]
        self.assertEqual([f["C"] for f in filas], [5585] * 7)
        self.assertEqual([f["D"] for f in filas], [4135950400, 4135950400, 1365950100, 1435010400, 6135950400, 1435010400, 6135950400])
        self.assertEqual([f["M"] for f in filas], list(range(1, 8)))
        self.assertEqual(filas[0]["P"], 80000002)
        self.assertEqual((filas[0]["F"], filas[0]["BX"], filas[0]["BV"]), (240000, 3, 12))
        self.assertEqual(filas[2]["F"], 255240)
        self.assertIsNone(hoja.cell(row=17, column=1).value)

    def test_aspecto_igual_al_modelo_de_siigo(self):
        hoja = load_workbook(io.BytesIO(self.generar().content)).active
        for coordenada in ("A1", "A2", "A3", "A5", "DY5"):
            self.assertEqual(hoja[coordenada].fill.fgColor.rgb, "0099CCFF", coordenada)
        self.assertEqual((hoja["A2"].font.name, hoja["A2"].font.sz, hoja["A2"].font.b), ("Verdana", 18, True))
        self.assertEqual((hoja["A5"].font.name, hoja["A5"].font.b), ("Verdana", True))
        self.assertEqual((hoja["C6"].font.name, hoja["C6"].font.b), ("Verdana", False))
        self.assertEqual(hoja["F6"].number_format, r"##,##0.00_);[Red]\(##,##0.00\)")
        self.assertEqual(hoja["F7"].border.bottom.style, "thin")
        self.assertIn("1 posición alfanumérica", hoja["A5"].comment.text)
        self.assertEqual(sum(1 for celda in hoja[5] if celda.comment), 129)

    def test_descargar_lo_seleccionado_siempre(self):
        self.generar()
        self.pedido1.refresh_from_db()
        self.config.refresh_from_db()
        self.assertEqual(self.pedido1.siigo_numero, 5584)
        self.assertEqual(self.config.siguiente_numero, 5586)

        # Se puede repetir cuantas veces se quiera, con el número inicial que se escoja.
        for _ in range(2):
            hoja = load_workbook(io.BytesIO(self.generar().content)).active
            self.assertEqual({hoja.cell(row=n, column=3).value for n in range(6, 17)}, {5584, 5585})

        # Solo el pedido 2, con otro número: sale solo él y queda con ese número.
        hoja = load_workbook(io.BytesIO(self.generar(pedidos=[self.pedido2], numero_inicial="7000").content)).active
        self.assertEqual({hoja.cell(row=n, column=3).value for n in range(6, 13)}, {7000})
        self.assertIsNone(hoja.cell(row=13, column=1).value)
        self.pedido2.refresh_from_db()
        self.config.refresh_from_db()
        self.assertEqual((self.pedido2.siigo_numero, self.config.siguiente_numero), (7000, 7001))

        # La página siempre ofrece el número inicial y muestra la última factura de cada pedido.
        pagina = self.client.get(reverse("pedidos:siigo"), {"desde": "2026-11-01", "hasta": "2026-11-30"})
        self.assertContains(pagina, 'name="numero_inicial"')
        self.assertContains(pagina, 'value="7001"')
        self.assertContains(pagina, "F-003 7000")

    def test_hay_que_marcar_algo_y_escribir_el_numero(self):
        self.assertEqual(self.generar(pedidos=[]).status_code, 302)
        self.assertEqual(self.generar(numero_inicial="").status_code, 302)
        self.assertEqual(self.generar(pedidos=[self.de_otro_fondo]).status_code, 302)  # no es de MACS
        self.pedido1.refresh_from_db()
        self.assertIsNone(self.pedido1.siigo_numero)

    def test_numero_inicial_manual(self):
        hoja = load_workbook(io.BytesIO(self.generar(numero_inicial="9000").content)).active
        self.assertEqual(hoja["C6"].value, 9000)
        self.config.refresh_from_db()
        self.assertEqual(self.config.siguiente_numero, 9002)

    def test_producto_sin_codigo_siigo_no_se_exporta(self):
        ProductoPresentacion.objects.filter(pk=self.cafe.pk).update(codigo_siigo="")
        respuesta = self.client.get(reverse("pedidos:siigo"), {"desde": "2026-11-01", "hasta": "2026-11-30"})
        self.assertContains(respuesta, "no tiene código Siigo")
        hoja = load_workbook(io.BytesIO(self.generar().content)).active  # el 2 se ignora aunque venga marcado
        self.assertEqual({hoja.cell(row=n, column=3).value for n in range(6, 10)}, {5584})
        self.pedido2.refresh_from_db()
        self.assertIsNone(self.pedido2.siigo_numero)

    def test_fuera_de_rango_y_cancelados_no_salen(self):
        Pedido.objects.filter(pk=self.pedido1.pk).update(estado=Pedido.ESTADO_CANCELADO)
        respuesta = self.client.get(reverse("pedidos:siigo"), {"desde": "2026-11-04", "hasta": "2026-11-30"})
        self.assertNotContains(respuesta, self.pedido2.numero)
        respuesta = self.client.get(reverse("pedidos:siigo"), {"desde": "2026-11-01", "hasta": "2026-11-30"})
        self.assertNotContains(respuesta, self.pedido1.numero)

    def test_permisos(self):
        solo_ver = get_user_model().objects.create_user(username="ver", password="x")
        solo_ver.user_permissions.add(Permission.objects.get(codename="view_pedido"))
        self.client.force_login(solo_ver)
        self.assertEqual(self.client.get(reverse("pedidos:siigo")).status_code, 200)
        self.assertEqual(self.generar().status_code, 403)
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(reverse("pedidos:siigo")).status_code, 403)


class DescripcionSiigoTest(TestCase):
    """Nombre del producto como en Siigo: NOMBRE *PRESENTACIÓN, con la cantidad pegada a su unidad."""

    def descripcion(self, nombre, presentacion):
        from types import SimpleNamespace

        from .siigo import _texto, descripcion_producto

        origen = SimpleNamespace(producto=SimpleNamespace(nombre=nombre), presentacion=SimpleNamespace(nombre=presentacion))
        return _texto(descripcion_producto(SimpleNamespace(combo_id=None), origen)).strip()

    def test_formato(self):
        self.assertEqual(self.descripcion("Leche Bolsa", "900 ml"), "LECHE BOLSA *900ML")
        self.assertEqual(self.descripcion("Arepa rellena de queso", "*80GRS X 10 UNDS"), "AREPA RELLENA DE QUESO *80GRS X 10 UNDS")
        self.assertEqual(self.descripcion("Queso", "500 g x 2 und"), "QUESO *500G X 2 UND")
        self.assertEqual(self.descripcion("Café", "1.5 kg"), "CAFÉ *1.5KG")
