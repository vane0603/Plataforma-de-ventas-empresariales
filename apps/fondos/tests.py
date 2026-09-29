from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.carrito.models import Carrito, CarritoItem
from apps.catalogos.models import Categoria, Marca, Presentacion, UnidadMedida
from apps.pedidos.models import Pedido
from apps.productos.models import Producto, ProductoPresentacion
from .models import FondoEmpleado, SolicitudDescuentoNomina


class FlujoNominaTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.cliente = User.objects.create_user(
            username="cliente", password="clave12345", email="cliente@example.com"
        )
        self.gestor = User.objects.create_user(
            username="gestor", password="clave12345", email="gestor@example.com"
        )

        unidad = UnidadMedida.objects.create(nombre="Gramo", abreviatura="g")
        presentacion = Presentacion.objects.create(nombre="500 g", cantidad=500, unidad=unidad)
        categoria = Categoria.objects.create(nombre="Prueba")
        marca = Marca.objects.create(nombre="Marca prueba")
        producto = Producto.objects.create(
            codigo="PR-001", nombre="Producto prueba", categoria=categoria, marca=marca
        )
        self.producto_presentacion = ProductoPresentacion.objects.create(
            producto=producto,
            codigo="PR-001-500",
            presentacion=presentacion,
            precio=Decimal("50000.00"),
        )
        self.fondo = FondoEmpleado.objects.create(
            nombre="Fondo prueba", correo="fondo@example.com"
        )
        self.fondo.gestores.add(self.gestor)

    def test_flujo_completo_nomina(self):
        self.client.force_login(self.cliente)
        carrito = Carrito.objects.create(usuario=self.cliente)
        CarritoItem.objects.create(
            carrito=carrito,
            presentacion=self.producto_presentacion,
            cantidad=2,
            precio_unitario=Decimal("50000.00"),
        )

        respuesta = self.client.post(
            reverse("pedidos:checkout"),
            {
                "direccion_entrega": "Calle 1 # 2-3",
                "ciudad": "Bogotá",
                "metodo_pago": Pedido.METODO_NOMINA,
                "observaciones": "",
            },
        )
        pedido = Pedido.objects.get(usuario=self.cliente)
        self.assertRedirects(
            respuesta,
            reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]),
        )
        self.assertEqual(pedido.items.count(), 1)
        self.assertEqual(pedido.total, Decimal("100000.00"))

        respuesta = self.client.post(
            reverse("fondos:solicitar_descuento_nomina", args=[pedido.id]),
            {
                "fondo": self.fondo.id,
                "nombre_completo": "Cliente de Prueba",
                "documento": "123456789",
                "telefono": "3001234567",
                "correo": "cliente@example.com",
                "empresa": "Empresa prueba",
                "numero_afiliado": "A-10",
                "observaciones_usuario": "",
            },
        )
        solicitud = SolicitudDescuentoNomina.objects.get(pedido=pedido)
        self.assertRedirects(
            respuesta,
            reverse("fondos:solicitud_exitosa", args=[solicitud.id]),
        )
        self.assertEqual(solicitud.valor_solicitado, Decimal("100000.00"))

        self.client.force_login(self.gestor)
        respuesta = self.client.post(
            reverse("fondos:gestion_detalle", args=[solicitud.id]),
            {
                "vinculacion_validada": "True",
                "estado": SolicitudDescuentoNomina.ESTADO_APROBADA,
                "cupo_disponible_reportado": "150000",
                "valor_aprobado": "100000",
                "referencia_fondo": "REF-001",
                "respuesta_fondo": "Aprobado",
            },
        )
        self.assertRedirects(
            respuesta,
            reverse("fondos:gestion_detalle", args=[solicitud.id]),
        )
        solicitud.refresh_from_db()
        pedido.refresh_from_db()
        self.assertTrue(solicitud.vinculacion_validada)
        self.assertEqual(solicitud.estado, SolicitudDescuentoNomina.ESTADO_APROBADA)
        self.assertEqual(pedido.estado, Pedido.ESTADO_APROBADO_NOMINA)
