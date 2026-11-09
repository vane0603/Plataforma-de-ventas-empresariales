"""
Reporte de pedidos en Excel para la administración.

Filtros: rango de fechas de creación, estado y medio de pago. El archivo tiene
dos hojas: "Pedidos" (una fila por pedido, con totales) y "Productos" (el
detalle de cada pedido).
"""

import io
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from .models import Pedido, PedidoItem

COLOR_ENCABEZADO = "0E2A4F"
TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FORMATO_PESOS = '"$"#,##0'

COLUMNAS_PEDIDOS = [
    ("Pedido", 22),
    ("Fecha", 17),
    ("Cliente", 28),
    ("Ciudad", 18),
    ("Tipo de entrega", 18),
    ("Dirección de entrega", 32),
    ("Medio de pago", 20),
    ("Estado", 24),
    ("Fondo", 22),
    ("Finca / punto", 22),
    ("Despachado", 17),
    ("Entregado", 17),
    ("Recibió", 22),
    ("Subtotal", 14),
    ("Descuento", 14),
    ("Total", 14),
    ("Por nómina", 14),
    ("Saldo", 14),
]
# Las últimas columnas de "Pedidos" (subtotal, descuento, total, nómina, saldo) llevan total al final.
COLUMNAS_SUMADAS = 5

COLUMNAS_PRODUCTOS = [
    ("Pedido", 22),
    ("Fecha", 17),
    ("Estado", 24),
    ("Producto", 32),
    ("Referencia", 14),
    ("Presentación", 20),
    ("Cantidad", 10),
    ("Precio unitario", 15),
    ("Subtotal", 14),
    ("Descuento", 14),
]


@dataclass
class Filtros:
    desde: date | None = None
    hasta: date | None = None
    estado: str = ""
    metodo: str = ""
    tipo: str = ""
    errores: list = field(default_factory=list)

    @classmethod
    def desde_peticion(cls, datos):
        filtros = cls(
            estado=datos.get("estado", "") if datos.get("estado") in dict(Pedido.ESTADOS) else "",
            metodo=datos.get("metodo", "") if datos.get("metodo") in dict(Pedido.METODOS_PAGO) else "",
            tipo=datos.get("tipo", "") if datos.get("tipo") in dict(Pedido.TIPOS_ENTREGA) else "",
        )
        for nombre in ("desde", "hasta"):
            texto = datos.get(nombre, "")
            try:
                setattr(filtros, nombre, date.fromisoformat(texto) if texto else None)
            except ValueError:
                filtros.errores.append(f"La fecha «{texto}» no es válida.")
        if filtros.desde and filtros.hasta and filtros.desde > filtros.hasta:
            filtros.errores.append("La fecha «desde» es posterior a «hasta».")
        return filtros

    def aplicar(self, pedidos):
        if self.desde:
            pedidos = pedidos.filter(created_at__gte=timezone.make_aware(datetime.combine(self.desde, time.min)))
        if self.hasta:
            fin = datetime.combine(self.hasta + timedelta(days=1), time.min)
            pedidos = pedidos.filter(created_at__lt=timezone.make_aware(fin))
        if self.estado:
            pedidos = pedidos.filter(estado=self.estado)
        if self.metodo:
            pedidos = pedidos.filter(metodo_pago=self.metodo)
        if self.tipo:
            pedidos = pedidos.filter(tipo_entrega=self.tipo)
        return pedidos

    def nombre_archivo(self):
        partes = ["pedidos"]
        if self.desde or self.hasta:
            partes.append(f"{self.desde or 'inicio'}_a_{self.hasta or timezone.localdate()}")
        else:
            partes.append(f"{timezone.localdate()}")
        return "_".join(partes) + ".xlsx"


def pedidos_del_reporte(filtros):
    return filtros.aplicar(
        Pedido.objects
        .select_related("usuario", "entrega", "solicitud_nomina__fondo", "solicitud_nomina__finca")
        .order_by("-created_at", "-id")
    )


def resumen(pedidos):
    """Cantidad y total general, y el desglose por estado (para la vista previa)."""
    general = pedidos.aggregate(cantidad=Count("id"))
    general["total"] = pedidos.exclude(estado=Pedido.ESTADO_CANCELADO).aggregate(total=Sum("total"))["total"]
    por_estado = [
        {"estado": dict(Pedido.ESTADOS).get(fila["estado"], fila["estado"]), **fila}
        for fila in pedidos.order_by().values("estado").annotate(cantidad=Count("id"), total=Sum("total")).order_by("-cantidad")
    ]
    return {"cantidad": general["cantidad"], "total": general["total"] or Decimal("0"), "por_estado": por_estado}


def _fecha(valor):
    # Excel no admite fechas con zona horaria: se pasa a la hora de Colombia sin zona.
    return timezone.localtime(valor).replace(tzinfo=None) if valor else None


def _solicitud(pedido):
    try:
        return pedido.solicitud_nomina
    except Pedido.solicitud_nomina.RelatedObjectDoesNotExist:
        return None


def _entrega(pedido):
    try:
        return pedido.entrega
    except Pedido.entrega.RelatedObjectDoesNotExist:
        return None


def fila_pedido(pedido):
    solicitud, entrega = _solicitud(pedido), _entrega(pedido)
    return [
        pedido.numero,
        _fecha(pedido.created_at),
        pedido.nombre_cliente,
        pedido.ciudad,
        pedido.get_tipo_entrega_display(),
        pedido.direccion_entrega,
        pedido.get_metodo_pago_display(),
        pedido.get_estado_display(),
        str(solicitud.fondo) if solicitud else "",
        str(solicitud.finca) if solicitud and solicitud.finca_id else "",
        _fecha(pedido.despachado_en),
        _fecha(entrega.entregado_en) if entrega else None,
        entrega.recibido_por if entrega else "",
        pedido.subtotal,
        pedido.descuento,
        pedido.total,
        pedido.valor_nomina or Decimal("0"),
        pedido.saldo_pendiente,
    ]


def _preparar_hoja(hoja, columnas):
    from openpyxl.styles import Font, PatternFill

    hoja.append([titulo for titulo, _ in columnas])
    for indice, (celda, (_, ancho)) in enumerate(zip(hoja[1], columnas), start=1):
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor=COLOR_ENCABEZADO)
        hoja.column_dimensions[celda.column_letter].width = ancho
    hoja.freeze_panes = "A2"


def _formatear(hoja, columnas, desde_fila=2):
    titulos = [t for t, _ in columnas]
    for indice, titulo in enumerate(titulos, start=1):
        if titulo in ("Fecha", "Despachado", "Entregado"):
            formato = "dd/mm/yyyy hh:mm"
        elif titulo in ("Subtotal", "Descuento", "Total", "Por nómina", "Saldo", "Precio unitario"):
            formato = FORMATO_PESOS
        else:
            continue
        for fila in hoja.iter_rows(min_row=desde_fila, min_col=indice, max_col=indice):
            fila[0].number_format = formato


def generar_xlsx(pedidos):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Pedidos"
    _preparar_hoja(hoja, COLUMNAS_PEDIDOS)

    sumas = [Decimal("0")] * COLUMNAS_SUMADAS
    cantidad = 0
    for pedido in pedidos:
        fila = fila_pedido(pedido)
        hoja.append(fila)
        cantidad += 1
        # Los cancelados se listan, pero no suman.
        if pedido.estado != Pedido.ESTADO_CANCELADO:
            sumas = [a + b for a, b in zip(sumas, fila[-COLUMNAS_SUMADAS:])]

    if cantidad:
        hoja.auto_filter.ref = hoja.dimensions
        hoja.append([])
        hoja.append([f"{cantidad} pedidos"] + [""] * (len(COLUMNAS_PEDIDOS) - COLUMNAS_SUMADAS - 2) + ["TOTAL (sin cancelados)"] + sumas)
        for celda in hoja[hoja.max_row]:
            celda.font = Font(bold=True)
    _formatear(hoja, COLUMNAS_PEDIDOS)

    detalle = libro.create_sheet("Productos")
    _preparar_hoja(detalle, COLUMNAS_PRODUCTOS)
    items = (
        PedidoItem.objects
        .filter(pedido__in=pedidos.order_by().values("id"))
        .select_related("pedido")
        .order_by("-pedido__created_at", "-pedido__id", "id")
    )
    for item in items:
        detalle.append([
            item.pedido.numero, _fecha(item.pedido.created_at), item.pedido.get_estado_display(),
            item.producto_nombre, item.referencia, item.presentacion, item.cantidad,
            item.precio_unitario, item.subtotal, item.descuento,
        ])
    if detalle.max_row > 1:
        detalle.auto_filter.ref = detalle.dimensions
    _formatear(detalle, COLUMNAS_PRODUCTOS)

    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
