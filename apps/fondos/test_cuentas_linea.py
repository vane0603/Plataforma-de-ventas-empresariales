import io
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from apps.catalogos.models import Categoria, Marca, Presentacion, UnidadMedida
from apps.pedidos.models import Pedido, PedidoItem
from apps.productos.models import Producto, ProductoPresentacion
from .models import ConfiguracionSiigo, CuentaLineaSiigo, FondoEmpleado, SolicitudDescuentoNomina, cuenta_siigo
from .siigo_cuentas import ImportacionError, importar_cuentas_lineas

S = SolicitudDescuentoNomina


def excel_de_lineas(filas):
    """Como la tabla de Siigo: títulos arriba, encabezados en la fila 7 y celdas de texto con ceros."""
    libro = Workbook()
    hoja = libro.active
    hoja["A1"] = "MACS COMERCIALIZADORA"
    for _ in range(5):
        hoja.append([])
    hoja.append(["LINEA", "GRUPO", "CTA INVENT", "CTA COSTOS", "CTA VENTA", "CTA DEVOLU", "CTA COMPRA", "NOMBRE LINEA"])
    for fila in filas:
        hoja.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return SimpleUploadedFile("lineas.xlsx", salida.getvalue())


class CuentasPorLineaTest(TestCase):
    def test_cuenta_con_10_digitos(self):
        self.assertEqual(cuenta_siigo("41359504"), 4135950400)
        self.assertEqual(cuenta_siigo("5235950701"), 5235950701)
        self.assertIsNone(cuenta_siigo("00000000"))

    def test_importar_la_tabla_de_siigo(self):
        archivo = excel_de_lineas([
            ["010", "0001", "52953005", "61359533", "42950501", "41750501", "00000000", "SERVICIOS"],
            ["700", "0015", "14350104", "61359504", "41359504", "41750504", "00000000", "BEBIDAS"],
            ["", "", "", "", "", "", "", ""],
            ["700", "0099", "14350104", "61359504", "", "", "", "SIN CUENTA DE VENTA"],
        ])
        resultado = importar_cuentas_lineas(archivo)
        self.assertEqual((resultado.creadas, resultado.actualizadas, len(resultado.errores)), (2, 0, 1))
        bebidas = CuentaLineaSiigo.objects.get(linea=700, grupo=15)
        self.assertEqual((bebidas.cuenta_venta, bebidas.cuenta_inventario, bebidas.cuenta_costo, bebidas.nombre_linea),
                         ("41359504", "14350104", "61359504", "BEBIDAS"))

        # Volver a importar actualiza en vez de duplicar.
        resultado = importar_cuentas_lineas(excel_de_lineas([["700", "15", "14350104", "61359504", "41359599", "", "", "BEBIDAS"]]))
        self.assertEqual((resultado.creadas, resultado.actualizadas), (0, 1))
        self.assertEqual(CuentaLineaSiigo.objects.get(linea=700, grupo=15).cuenta_venta, "41359599")

    def test_archivo_sin_columnas(self):
        libro = Workbook()
        libro.active.append(["A", "B"])
        salida = io.BytesIO()
        libro.save(salida)
        with self.assertRaises(ImportacionError):
            importar_cuentas_lineas(SimpleUploadedFile("x.xlsx", salida.getvalue()))

    def test_importar_desde_el_admin(self):
        admin = get_user_model().objects.create_superuser(username="admin", password="x", email="a@example.com")
        self.client.force_login(admin)
        lista = self.client.get(reverse("admin:fondos_cuentalineasiigo_changelist"))
        self.assertContains(lista, "Importar desde Excel")
        respuesta = self.client.post(reverse("admin:fondos_cuentalineasiigo_importar"), {
            "archivo": excel_de_lineas([["700", "0015", "14350104", "61359504", "41359504", "41750504", "0", "BEBIDAS"]]),
        })
        self.assertRedirects(respuesta, reverse("admin:fondos_cuentalineasiigo_changelist"))
        self.assertTrue(CuentaLineaSiigo.objects.filter(linea=700, grupo=15).exists())

    def test_la_factura_usa_las_cuentas_de_la_linea(self):
        fondo = FondoEmpleado.objects.create(nombre="MACS")
        config = ConfiguracionSiigo.objects.create(fondo=fondo, siguiente_numero=100)
        CuentaLineaSiigo.objects.create(linea=700, grupo=15, cuenta_venta="41359599", cuenta_inventario="14350104",
                                        cuenta_costo="61359504", nombre_linea="BEBIDAS")
        unidad = UnidadMedida.objects.create(nombre="Mililitro", abreviatura="ml")
        categoria, marca = Categoria.objects.create(nombre="Lácteos"), Marca.objects.create(nombre="Tío Campo")

        def presentacion(codigo, codigo_siigo):
            producto = Producto.objects.create(codigo=codigo, nombre=f"Producto {codigo}", categoria=categoria, marca=marca)
            return ProductoPresentacion.objects.create(
                producto=producto, codigo=f"{codigo}-1", precio=Decimal("1000"), codigo_siigo=codigo_siigo,
                presentacion=Presentacion.objects.create(nombre=f"{codigo} ml", cantidad=1, unidad=unidad),
            )

        con_linea, sin_linea = presentacion("A", "700-15-9"), presentacion("B", "600-32-12")
        cliente = get_user_model().objects.create_user(username="ana", password="x")
        pedido = Pedido.objects.create(usuario=cliente, metodo_pago=Pedido.METODO_NOMINA, estado=Pedido.ESTADO_APROBADO_NOMINA,
                                       subtotal=2000, total=2000, direccion_entrega="Finca", ciudad="Madrid")
        for p in (con_linea, sin_linea):
            PedidoItem.objects.create(pedido=pedido, producto_presentacion=p, producto_nombre=p.producto.nombre, referencia=p.codigo,
                                      presentacion=p.presentacion.nombre, cantidad=1, precio_unitario=1000, subtotal=1000)
        S.objects.create(usuario=cliente, fondo=fondo, pedido=pedido, nombre_completo="Ana Pérez", documento="1000000001",
                         empresa="MACS", valor_solicitado=2000, valor_aprobado=2000, estado=S.ESTADO_APROBADA,
                         fecha_respuesta=timezone.make_aware(datetime(2026, 11, 6, 9, 0)))

        contador = get_user_model().objects.create_user(username="contador", password="x")
        contador.user_permissions.add(*Permission.objects.filter(codename__in=["view_pedido", "change_pedido"]))
        self.client.force_login(contador)
        pagina = self.client.get(reverse("pedidos:siigo"), {"desde": "2026-11-01", "hasta": "2026-11-30"})
        self.assertContains(pagina, "600-0032")  # avisa la línea sin cuentas
        respuesta = self.client.post(reverse("pedidos:siigo"), {
            "desde": "2026-11-01", "hasta": "2026-11-30", "numero_inicial": "100", "pedidos": [pedido.pk],
        })
        hoja = load_workbook(io.BytesIO(respuesta.content)).active
        cuentas = [hoja.cell(row=n, column=4).value for n in range(6, 13)]
        self.assertEqual(cuentas, [
            4135959900, config.cuenta_ingreso,          # ingreso: cuenta de venta de la línea 700-15 / por defecto
            config.cuenta_cartera,
            1435010400, 6135950400,                     # inventario y costo de la línea 700-15
            config.cuenta_inventario, config.cuenta_costo,  # línea sin fila: las del fondo
        ])


class CuentasOpcionalesTest(TestCase):
    def test_inventario_y_costo_en_ceros_quedan_vacios(self):
        importar_cuentas_lineas(excel_de_lineas([["020", "0001", "00000000", "", "41359506", "", "", "SERVICIOS"]]))
        linea = CuentaLineaSiigo.objects.get(linea=20, grupo=1)
        self.assertEqual((linea.cuenta_venta, linea.cuenta_inventario, linea.cuenta_costo), ("41359506", "", ""))
