from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.carrito.models import Carrito, CarritoItem
from apps.core import municipios
from apps.promociones.models import Combo

from .models import Pedido


class MunicipiosTest(TestCase):
    def test_datos_completos_del_dane(self):
        departamentos = municipios.departamentos()
        self.assertEqual(len(departamentos), 33)
        self.assertEqual(sum(len(d["municipios"]) for d in departamentos), 1122)
        antioquia = next(d for d in departamentos if d["nombre"] == "Antioquia")
        self.assertEqual(len(antioquia["municipios"]), 125)
        self.assertIn("Medellín", antioquia["municipios"])

    def test_buscar_sin_importar_tildes_ni_mayusculas(self):
        self.assertEqual(municipios.buscar("bogota"), ("Bogotá, D.C.", "Bogotá, D.C."))
        self.assertEqual(municipios.buscar("MEDELLIN"), ("Antioquia", "Medellín"))
        self.assertEqual(municipios.buscar("madrid", "cundinamarca"), ("Cundinamarca", "Madrid"))

    def test_nombre_repetido_exige_departamento(self):
        with self.assertRaises(municipios.MunicipioInvalido):
            municipios.buscar("Armenia")
        self.assertEqual(municipios.buscar("Armenia", "Quindío"), ("Quindío", "Armenia"))

    def test_municipio_inexistente_o_de_otro_departamento(self):
        for municipio, departamento in (("Ciudad Gótica", ""), ("Medellín", "Cundinamarca")):
            with self.assertRaises(municipios.MunicipioInvalido):
                municipios.buscar(municipio, departamento)

    def test_etiqueta(self):
        self.assertEqual(municipios.etiqueta("Cundinamarca", "Madrid"), "Madrid, Cundinamarca")
        self.assertEqual(municipios.etiqueta("Bogotá, D.C.", "Bogotá, D.C."), "Bogotá, D.C.")


class CheckoutMunicipiosTest(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="ana", password="x", email="ana@example.com")
        combo = Combo.objects.create(codigo="C-1", nombre="Combo", precio=Decimal("20000"), stock=5)
        carrito = Carrito.objects.create(usuario=self.usuario, activo=True)
        CarritoItem.objects.create(carrito=carrito, combo=combo, cantidad=1, precio_unitario=combo.precio)
        self.client.force_login(self.usuario)

    def comprar(self, **datos):
        formulario = {"metodo_pago": Pedido.METODO_OTRO, "direccion_entrega": "Carrera 1A # 8A-37"}
        formulario.update(datos)
        return self.client.post(reverse("pedidos:checkout"), formulario)

    def test_listas_desplegables_con_bogota_por_defecto(self):
        respuesta = self.client.get(reverse("pedidos:checkout"))
        self.assertContains(respuesta, '<option value="Bogotá, D.C." selected>', count=2)
        self.assertContains(respuesta, '<select class="form-select form-select-lg" id="id_departamento"')
        self.assertContains(respuesta, 'id="tc-municipios"')
        self.assertEqual(respuesta.context["municipios_del_departamento"], ["Bogotá, D.C."])

    def test_guarda_municipio_y_departamento(self):
        self.comprar(departamento="Cundinamarca", ciudad="Madrid")
        self.assertEqual(Pedido.objects.get().ciudad, "Madrid, Cundinamarca")

    def test_rechaza_municipio_que_no_es_del_departamento(self):
        respuesta = self.comprar(departamento="Cundinamarca", ciudad="Medellín")
        self.assertFalse(Pedido.objects.exists())
        self.assertContains(respuesta, "Selecciona un municipio de la lista.")
        # Conserva el departamento elegido y muestra sus municipios.
        self.assertEqual(respuesta.context["departamento_sel"], "Cundinamarca")
        self.assertIn("Madrid", respuesta.context["municipios_del_departamento"])

    def test_sin_municipio(self):
        respuesta = self.comprar(departamento="Antioquia", ciudad="")
        self.assertFalse(Pedido.objects.exists())
        self.assertContains(respuesta, "Selecciona el municipio de entrega.")

    def test_con_nomina_no_se_pide_municipio(self):
        self.comprar(metodo_pago=Pedido.METODO_NOMINA, direccion_entrega="", departamento="", ciudad="")
        self.assertEqual(Pedido.objects.get().metodo_pago, Pedido.METODO_NOMINA)
