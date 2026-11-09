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
from apps.fondos.models import Finca, FondoEmpleado, SolicitudDescuentoNomina
from apps.productos.models import Producto, ProductoPresentacion
from .models import Pedido, PedidoItem


class ReportePedidosTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin", password="x")
        self.admin.user_permissions.add(Permission.objects.get(codename="view_pedido"))
        self.cliente = User.objects.create_user(username="ana", password="x", first_name="Ana", last_name="Pérez")

        self.octubre = self.pedido(Pedido.METODO_ELECTRONICO, Pedido.ESTADO_PAGADO, "30000", datetime(2026, 10, 5, 9, 0))
        unidad = UnidadMedida.objects.create(nombre="Gramo", abreviatura="g")
        producto = Producto.objects.create(
            codigo="Q1", nombre="Queso campesino",
            categoria=Categoria.objects.create(nombre="Lácteos"), marca=Marca.objects.create(nombre="Tío Campo"),
        )
        presentacion = ProductoPresentacion.objects.create(
            producto=producto, codigo="Q1-500",
            presentacion=Presentacion.objects.create(nombre="500 g", cantidad=500, unidad=unidad),
            precio=Decimal("15000"),
        )
        PedidoItem.objects.create(
            pedido=self.octubre, producto_presentacion=presentacion, producto_nombre="Queso campesino",
            referencia="Q1-500", presentacion="500 g", cantidad=2, precio_unitario=Decimal("15000"), subtotal=Decimal("30000"),
        )
        self.cancelado = self.pedido(Pedido.METODO_OTRO, Pedido.ESTADO_CANCELADO, "8000", datetime(2026, 10, 20, 9, 0))
        self.septiembre = self.pedido(Pedido.METODO_NOMINA, Pedido.ESTADO_APROBADO_NOMINA, "50000", datetime(2026, 9, 10, 9, 0),
                                      valor_nomina=Decimal("50000"))
        fondo = FondoEmpleado.objects.create(nombre="Fondo Flores")
        SolicitudDescuentoNomina.objects.create(
            usuario=self.cliente, fondo=fondo, finca=Finca.objects.create(fondo=fondo, nombre="La Esperanza"),
            pedido=self.septiembre, nombre_completo="Ana Pérez", documento="123", empresa="Flores SAS",
            valor_solicitado=Decimal("50000"), valor_aprobado=Decimal("50000"),
            estado=SolicitudDescuentoNomina.ESTADO_APROBADA,
        )

    def pedido(self, metodo, estado, total, creado, **extra):
        pedido = Pedido.objects.create(
            usuario=self.cliente, metodo_pago=metodo, estado=estado, subtotal=Decimal(total), total=Decimal(total),
            direccion_entrega="Calle 1", ciudad="Bogotá", **extra,
        )
        Pedido.objects.filter(pk=pedido.pk).update(created_at=timezone.make_aware(creado))
        pedido.refresh_from_db()
        return pedido

    def libro(self, **filtros):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("pedidos:reporte"), {"formato": "xlsx", **filtros})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("attachment", respuesta["Content-Disposition"])
        return load_workbook(io.BytesIO(respuesta.content))

    def test_solo_con_permiso(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(reverse("pedidos:reporte")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("pedidos:reporte")).status_code, 302)

    def test_vista_previa_y_enlace_de_descarga(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("pedidos:reporte"), {"desde": "2026-10-01"})
        self.assertContains(respuesta, self.octubre.numero)
        self.assertContains(respuesta, self.cancelado.numero)
        self.assertNotContains(respuesta, self.septiembre.numero)
        self.assertContains(respuesta, "$30.000")  # el cancelado no suma
        self.assertContains(respuesta, "formato=xlsx")
        self.assertContains(respuesta, "desde=2026-10-01")

    def test_excel_con_todos_los_pedidos_y_totales(self):
        hoja = self.libro()["Pedidos"]
        filas = list(hoja.iter_rows(values_only=True))
        self.assertEqual(filas[0][0], "Pedido")
        numeros = [f[0] for f in filas[1:4]]
        self.assertEqual(numeros, [self.cancelado.numero, self.octubre.numero, self.septiembre.numero])
        nomina = filas[3]
        self.assertEqual(nomina[8], "Fondo Flores")
        self.assertEqual(nomina[9], "La Esperanza")
        self.assertEqual(nomina[2], "Ana Pérez")
        total = filas[-1]
        self.assertEqual(total[0], "3 pedidos")
        self.assertEqual(total[15], 80000)  # 30.000 + 50.000, sin el cancelado

    def test_hoja_de_productos(self):
        filas = list(self.libro()["Productos"].iter_rows(values_only=True))
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[1][0], self.octubre.numero)
        self.assertEqual(filas[1][3:7], ("Queso campesino", "Q1-500", "500 g", 2))
        self.assertEqual(filas[1][8], 30000)

    def test_filtros_de_estado_y_medio_de_pago(self):
        hoja = self.libro(metodo=Pedido.METODO_NOMINA)["Pedidos"]
        self.assertEqual(hoja.cell(row=2, column=1).value, self.septiembre.numero)
        self.assertEqual(hoja.cell(row=3, column=1).value, None)

        hoja = self.libro(estado=Pedido.ESTADO_PAGADO, hasta="2026-10-31")["Pedidos"]
        self.assertEqual(hoja.cell(row=2, column=1).value, self.octubre.numero)

    def test_fecha_invalida_no_descarga(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("pedidos:reporte"), {"desde": "2026-12-01", "hasta": "2026-01-01", "formato": "xlsx"})
        self.assertContains(respuesta, "posterior")
        self.assertNotIn("attachment", respuesta.get("Content-Disposition", ""))

    def test_sin_pedidos_genera_excel_vacio(self):
        hoja = self.libro(desde="2030-01-01")["Pedidos"]
        self.assertEqual(hoja.max_row, 1)
