"""
API REST v1. Cada endpoint es una capa delgada sobre los servicios y
formularios que ya usa la web, así ambas aplican las mismas reglas.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.carrito.services import CarritoError, fijar_cantidad, resumen_carrito
from apps.carrito.views import obtener_carrito
from apps.catalogos.models import Categoria
from apps.fondos.forms import CargaPadronForm, RespuestaFondoForm, SolicitudDescuentoNominaForm
from apps.fondos.models import FondoEmpleado, SolicitudDescuentoNomina
from apps.fondos.reportes import (
    ReporteError,
    archivo_reporte,
    cerrar_corte,
    periodo_desde_texto,
    periodo_por_defecto,
    resumen,
    solicitudes_del_periodo,
)
from apps.fondos.services import (
    DecisionInvalida,
    SolicitudError,
    aplicar_decision,
    crear_solicitud,
    importar_padron,
)
from apps.pagos.services import PagoError, iniciar_pago
from apps.pedidos.acceso import pedido_accesible, recordar_pedido
from apps.pedidos.forms import CheckoutForm
from apps.pedidos.models import Pedido
from apps.pedidos.services import PedidoError, cancelar_pedido, crear_pedido_desde_carrito, definir_pago_saldo
from apps.productos.consultas import ORDENES, buscar, productos_para_tarjetas
from apps.promociones.models import Combo

from . import serializers as s
from .permisos import EsGestorDeFondo, fondos_del_gestor, solicitudes_del_gestor


def _errores(form):
    return {campo: [str(e) for e in errores] for campo, errores in form.errors.items()}


def _datos_planos(request):
    """Convierte el cuerpo (JSON o formulario) en un dict que entienden los forms de Django."""
    datos = {}
    for clave, valor in request.data.items():
        if isinstance(valor, bool):
            valor = "on" if valor else ""
        datos[clave] = "" if valor is None else valor
    return datos


# =================================================================== CATÁLOGO

class CategoriaLista(generics.ListAPIView):
    """Categorías activas, en el orden del menú."""

    permission_classes = [AllowAny]
    serializer_class = s.CategoriaSerializer
    pagination_class = None
    queryset = Categoria.objects.filter(activo=True).order_by("orden", "nombre")


@extend_schema(parameters=[
    OpenApiParameter("q", str, description="Texto a buscar (nombre, marca, código)."),
    OpenApiParameter("categoria", int, description="ID de categoría."),
    OpenApiParameter("orden", str, enum=list(ORDENES)),
])
class ProductoLista(generics.ListAPIView):
    """Productos activos con sus presentaciones y precio desde."""

    permission_classes = [AllowAny]
    serializer_class = s.ProductoSerializer

    def get_queryset(self):
        productos = buscar(productos_para_tarjetas(), self.request.query_params.get("q"))
        categoria = self.request.query_params.get("categoria")
        if categoria and categoria.isdigit():
            productos = productos.filter(categoria_id=categoria)
        orden = self.request.query_params.get("orden", "relevancia")
        return productos.order_by(*ORDENES.get(orden, ORDENES["relevancia"]))


class ProductoDetalle(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = s.ProductoSerializer
    queryset = productos_para_tarjetas()


class ComboLista(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = s.ComboSerializer
    queryset = Combo.objects.filter(activo=True, stock__gt=0).order_by("-destacado", "orden", "nombre")


# =================================================================== CARRITO

def _respuesta_carrito(carrito, **extra):
    items = carrito.items.select_related("presentacion__producto", "presentacion__presentacion", "combo")
    cantidad, total = resumen_carrito(carrito)
    return Response({
        "items": s.CarritoItemSerializer(items, many=True).data,
        "cantidad_total": cantidad,
        "total": str(total),
        **extra,
    })


@extend_schema(methods=["GET"], responses=s.CarritoSerializer, summary="Ver el carrito")
@extend_schema(methods=["DELETE"], responses=s.CarritoSerializer, summary="Vaciar el carrito")
@api_view(["GET", "DELETE"])
@permission_classes([AllowAny])
def carrito(request):
    """El carrito es del usuario autenticado o, sin sesión, de la cookie de sesión."""
    carrito = obtener_carrito(request)
    if request.method == "DELETE":
        carrito.items.all().delete()
    return _respuesta_carrito(carrito)


@extend_schema(request=s.CantidadSerializer, responses=s.CarritoSerializer,
               summary="Fijar la cantidad de un ítem (0 lo elimina)")
@api_view(["POST"])
@permission_classes([AllowAny])
def carrito_items(request):
    entrada = s.CantidadSerializer(data=request.data)
    entrada.is_valid(raise_exception=True)
    carrito = obtener_carrito(request)
    try:
        cantidad, mensaje = fijar_cantidad(
            carrito, entrada.validated_data["tipo"], entrada.validated_data["id"], entrada.validated_data["cantidad"]
        )
    except CarritoError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return _respuesta_carrito(carrito, cantidad=cantidad, mensaje=mensaje)


# =================================================================== PEDIDOS

@extend_schema(methods=["GET"], responses=s.PedidoSerializer(many=True), summary="Mis pedidos")
@extend_schema(methods=["POST"], request=s.CheckoutSerializer, responses={201: s.PedidoCreadoSerializer},
               summary="Crear pedido con el carrito actual (sin sesión, excepto nómina)")
@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def pedidos(request):
    if request.method == "GET":
        if not request.user.is_authenticated:
            return Response({"detail": "Inicie sesión para ver sus pedidos."}, status=status.HTTP_401_UNAUTHORIZED)
        lista = Pedido.objects.filter(usuario=request.user).prefetch_related("items").order_by("-created_at")
        return Response(s.PedidoSerializer(lista[:50], many=True).data)

    carrito = obtener_carrito(request)
    if not carrito.items.exists():
        return Response({"detail": "El carrito está vacío."}, status=status.HTTP_400_BAD_REQUEST)

    form = CheckoutForm(_datos_planos(request), usuario=request.user)
    if not form.is_valid():
        return Response({"errores": _errores(form)}, status=status.HTTP_400_BAD_REQUEST)
    if form.requiere_login:
        return Response(
            {"detail": "El descuento por nómina requiere autenticación."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        pedido = crear_pedido_desde_carrito(
            carrito=carrito,
            usuario=request.user if request.user.is_authenticated else None,
            metodo_pago=form.cleaned_data["metodo_pago"],
            direccion=form.cleaned_data["direccion_entrega"].strip(),
            ciudad=form.cleaned_data["ciudad"].strip(),
            observaciones=form.cleaned_data["observaciones"].strip(),
            contacto=form.datos_contacto(),
            autoriza_datos=form.cleaned_data["autoriza_tratamiento"],
        )
    except PedidoError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if pedido.es_invitado:
        recordar_pedido(request, pedido)
    return Response(s.PedidoCreadoSerializer(pedido).data, status=status.HTTP_201_CREATED)


@extend_schema(responses=s.PedidoSerializer)
@api_view(["GET"])
@permission_classes([AllowAny])
def pedido_detalle(request, pedido_id):
    return Response(s.PedidoSerializer(pedido_accesible(request, pedido_id)).data)


@extend_schema(responses=s.PedidoSerializer, summary="Consultar un pedido con su código de seguimiento")
@api_view(["GET"])
@permission_classes([AllowAny])
def pedido_seguimiento(request, codigo):
    pedido = get_object_or_404(Pedido, codigo_acceso=codigo)
    if not pedido.es_invitado and request.user != pedido.usuario:
        return Response({"detail": "Inicie sesión para ver este pedido."}, status=status.HTTP_401_UNAUTHORIZED)
    if pedido.es_invitado:
        recordar_pedido(request, pedido)
    return Response(s.PedidoSerializer(pedido).data)


@extend_schema(request=None, responses=s.PedidoSerializer)
@api_view(["POST"])
@permission_classes([AllowAny])
def pedido_cancelar(request, pedido_id):
    pedido = pedido_accesible(request, pedido_id)
    try:
        pedido = cancelar_pedido(pedido, usuario=request.user if request.user.is_authenticated else None)
    except PedidoError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response(s.PedidoSerializer(pedido).data)


@extend_schema(
    request={"application/json": {"type": "object", "properties": {"metodo_pago_saldo": {"enum": ["ELECTRONICO", "OTRO"]}}}},
    responses=s.PedidoSerializer,
    summary="Tras aprobación parcial o rechazo: pagar el saldo con otro medio",
)
@api_view(["POST"])
@permission_classes([AllowAny])
def pedido_pagar_saldo(request, pedido_id):
    pedido = pedido_accesible(request, pedido_id)
    try:
        pedido = definir_pago_saldo(pedido, request.data.get("metodo_pago_saldo", ""))
    except PedidoError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response(s.PedidoSerializer(pedido).data)


@extend_schema(
    request=None,
    responses={200: {"type": "object", "properties": {"url": {"type": "string"}, "referencia": {"type": "string"}}}},
    summary="Iniciar pago en línea: devuelve la URL del checkout de la pasarela",
)
@api_view(["POST"])
@permission_classes([AllowAny])
def pedido_pago_en_linea(request, pedido_id):
    pedido = pedido_accesible(request, pedido_id)
    try:
        transaccion, url = iniciar_pago(pedido, correo=pedido.correo_notificacion)
    except PagoError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response({"url": url, "referencia": transaccion.referencia})


# =================================================================== NÓMINA (comprador)

class FondoLista(generics.ListAPIView):
    """Fondos de empleados activos con sus fincas (puntos de entrega)."""

    serializer_class = s.FondoConFincasSerializer
    pagination_class = None
    queryset = FondoEmpleado.objects.filter(activo=True).prefetch_related("fincas").order_by("nombre")


@extend_schema(methods=["GET"], responses=s.SolicitudSerializer(many=True), summary="Mis solicitudes de nómina")
@extend_schema(methods=["POST"], request=s.SolicitudEntradaSerializer, responses={201: s.SolicitudSerializer},
               summary="Solicitar descuento por nómina para un pedido")
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def solicitudes_nomina(request):
    if request.method == "GET":
        lista = (
            SolicitudDescuentoNomina.objects.filter(usuario=request.user)
            .select_related("fondo", "pedido").order_by("-fecha_solicitud")
        )
        return Response(s.SolicitudSerializer(lista[:50], many=True).data)

    pedido = get_object_or_404(
        Pedido, id=request.data.get("pedido"), usuario=request.user, metodo_pago=Pedido.METODO_NOMINA
    )
    form = SolicitudDescuentoNominaForm(_datos_planos(request))
    if not form.is_valid():
        return Response({"errores": _errores(form)}, status=status.HTTP_400_BAD_REQUEST)
    try:
        solicitud = crear_solicitud(pedido, form, request.user)
    except SolicitudError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response(s.SolicitudSerializer(solicitud).data, status=status.HTTP_201_CREATED)


# =================================================================== FONDO (gestores)

@extend_schema(parameters=[
    OpenApiParameter("estado", str, enum=[c for c, _ in SolicitudDescuentoNomina.ESTADOS]),
    OpenApiParameter("fondo", int),
])
class GestorSolicitudLista(generics.ListAPIView):
    """Solicitudes de los fondos que gestiona el usuario."""

    permission_classes = [EsGestorDeFondo]
    serializer_class = s.SolicitudGestorSerializer

    def get_queryset(self):
        solicitudes = solicitudes_del_gestor(self.request.user)
        estado = self.request.query_params.get("estado")
        if estado:
            solicitudes = solicitudes.filter(estado=estado)
        fondo = self.request.query_params.get("fondo")
        if fondo and fondo.isdigit():
            solicitudes = solicitudes.filter(fondo_id=fondo)
        return solicitudes.order_by("fecha_solicitud")


class GestorSolicitudDetalle(generics.RetrieveAPIView):
    permission_classes = [EsGestorDeFondo]
    serializer_class = s.SolicitudGestorSerializer

    def get_queryset(self):
        return solicitudes_del_gestor(self.request.user)


@extend_schema(request=s.DecisionSerializer, responses=s.SolicitudGestorSerializer,
               summary="Registrar la decisión del fondo (total, parcial o rechazo)")
@api_view(["POST"])
@permission_classes([EsGestorDeFondo])
def gestor_decision(request, solicitud_id):
    solicitud = get_object_or_404(solicitudes_del_gestor(request.user), id=solicitud_id)
    if not solicitud.esta_pendiente:
        return Response({"detail": "Esta solicitud ya fue decidida."}, status=status.HTTP_409_CONFLICT)
    datos = _datos_planos(request)
    if "vinculacion_validada" in request.data:
        datos["vinculacion_validada"] = "True" if request.data["vinculacion_validada"] in (True, "true", "True", "1", 1) else "False"
    form = RespuestaFondoForm(datos, solicitud=solicitud)
    if not form.is_valid():
        return Response({"errores": _errores(form)}, status=status.HTTP_400_BAD_REQUEST)
    d = form.cleaned_data
    try:
        solicitud = aplicar_decision(
            solicitud,
            estado=d["estado"],
            valor_aprobado=d["valor_aprobado"],
            vinculado=d["vinculacion_validada"],
            cupo_reportado=d["cupo_disponible_reportado"],
            referencia=d["referencia_fondo"],
            respuesta=d["respuesta_fondo"],
            origen=SolicitudDescuentoNomina.ORIGEN_GESTOR,
            usuario=request.user,
        )
    except DecisionInvalida as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response(s.SolicitudGestorSerializer(solicitud).data)


@extend_schema(
    request={"multipart/form-data": {"type": "object", "properties": {
        "archivo": {"type": "string", "format": "binary"},
        "desactivar_ausentes": {"type": "boolean"},
    }}},
    responses=s.ResultadoPadronSerializer,
    summary="Cargar el padrón de afiliados (CSV)",
)
@api_view(["POST"])
@permission_classes([EsGestorDeFondo])
@parser_classes([MultiPartParser, FormParser])
def gestor_padron(request, fondo_id):
    fondo = get_object_or_404(fondos_del_gestor(request.user), id=fondo_id)
    form = CargaPadronForm(request.data, request.FILES)
    if not form.is_valid():
        return Response({"errores": _errores(form)}, status=status.HTTP_400_BAD_REQUEST)
    resultado = importar_padron(
        fondo, form.cleaned_data["archivo"].read(), desactivar_ausentes=form.cleaned_data["desactivar_ausentes"]
    )
    return Response({
        "creados": resultado.creados,
        "actualizados": resultado.actualizados,
        "desactivados": resultado.desactivados,
        "errores": resultado.errores[:100],
    })


def _periodo(request):
    texto = request.query_params.get("mes")
    return periodo_desde_texto(texto) if texto else periodo_por_defecto()


@extend_schema(
    parameters=[
        OpenApiParameter("mes", str, description="AAAA-MM. Por defecto, el mes anterior."),
        OpenApiParameter("formato", str, enum=["json", "csv", "xlsx"]),
    ],
    responses={(200, "application/json"): s.ReporteSerializer, (200, "text/csv"): bytes,
               (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): bytes},
    summary="Reporte mensual de descuentos aprobados (json, csv o xlsx)",
)
@api_view(["GET"])
@permission_classes([EsGestorDeFondo])
def gestor_reporte(request, fondo_id):
    fondo = get_object_or_404(fondos_del_gestor(request.user), id=fondo_id)
    try:
        periodo = _periodo(request)
        formato = request.query_params.get("formato", "json")
        if formato != "json":
            contenido, tipo, nombre = archivo_reporte(fondo, periodo, formato)
            respuesta = HttpResponse(contenido, content_type=tipo)
            respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
            return respuesta
    except ReporteError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    corte, solicitudes = solicitudes_del_periodo(fondo, periodo)
    datos = resumen(solicitudes)
    return Response({
        "fondo": s.FondoSerializer(fondo).data,
        "periodo": f"{periodo:%Y-%m}",
        "cerrado": corte is not None,
        "cantidad": datos.cantidad,
        "total": f"{datos.total:.2f}",
        "solicitudes": s.SolicitudGestorSerializer(solicitudes, many=True).data,
    })


@extend_schema(
    request={"application/json": {"type": "object", "properties": {"mes": {"type": "string", "example": "2026-10"}}}},
    responses={201: s.CorteSerializer},
    summary="Cerrar el corte mensual (las solicitudes no vuelven a reportarse)",
)
@api_view(["POST"])
@permission_classes([EsGestorDeFondo])
@parser_classes([JSONParser, FormParser])
def gestor_cerrar_corte(request, fondo_id):
    fondo = get_object_or_404(fondos_del_gestor(request.user), id=fondo_id)
    try:
        texto = request.data.get("mes")
        periodo = periodo_desde_texto(texto) if texto else periodo_por_defecto()
        corte = cerrar_corte(fondo, periodo, usuario=request.user)
    except ReporteError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response(
        {"id": corte.id, "periodo": f"{periodo:%Y-%m}", "cantidad": corte.cantidad, "total": f"{corte.total:.2f}"},
        status=status.HTTP_201_CREATED,
    )
