"""
Exportación de pedidos por nómina al "modelo de importación de movimiento contable" de Siigo.

Cada pedido aprobado por el fondo es una factura (comprobante F-003 por defecto) con estas
secuencias, igual que el archivo de ejemplo de MACS:

1. Por cada producto: ingreso (crédito) por el valor antes del descuento, con su descuento.
2. Cuenta por cobrar al empleado (débito) por el total ya con el descuento, con el cruce a la factura.
3. Si hay descuento para empleados: descuento en ventas (débito) por el total descontado.
4. Por cada producto: salida de inventario (crédito) y costo de ventas (débito). Van en 0:
   Siigo calcula el costo; el valor de venta va en la columna "número de cheque" como en el ejemplo.

El usuario elige qué pedidos descargar y el número de factura inicial cada vez; el número usado
queda guardado en el pedido como referencia y el fondo propone el siguiente para la próxima vez.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.siigo import partes_codigo_siigo
from apps.fondos.models import ConfiguracionSiigo, CuentaLineaSiigo, SolicitudDescuentoNomina, cuenta_siigo

from .models import Pedido
from .siigo_formato import COLUMNAS, NOTAS

S = SolicitudDescuentoNomina
MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
LETRAS = [letra for letra, *_ in COLUMNAS]
ANCHO_DESCRIPCION = 50
COLOR_ENCABEZADO = "99CCFF"  # azul claro del modelo de Siigo


class SiigoError(Exception):
    pass


@dataclass
class Revision:
    """Pedidos listos y problemas que impiden exportar (productos sin código, documento inválido)."""

    pedidos: list = field(default_factory=list)
    problemas: list = field(default_factory=list)
    # Líneas-grupo sin fila en "Cuentas por línea Siigo": usan las cuentas por defecto del fondo.
    lineas_sin_cuenta: list = field(default_factory=list)


def fondos_con_siigo():
    return ConfiguracionSiigo.objects.filter(activo=True, fondo__activo=True).select_related("fondo").order_by("fondo__nombre")


def _rango(desde, hasta):
    inicio = timezone.make_aware(datetime.combine(desde, time.min))
    fin = timezone.make_aware(datetime.combine(hasta + timedelta(days=1), time.min))
    return inicio, fin


def pedidos_del_fondo(config, desde, hasta):
    """Pedidos con descuento aprobado (total o parcial) en el rango, según la fecha de aprobación."""
    inicio, fin = _rango(desde, hasta)
    return (
        Pedido.objects
        .filter(
            solicitud_nomina__fondo=config.fondo,
            solicitud_nomina__estado__in=(S.ESTADO_APROBADA, S.ESTADO_APROBADA_PARCIAL),
            solicitud_nomina__anonimizada_en__isnull=True,
            solicitud_nomina__fecha_respuesta__gte=inicio,
            solicitud_nomina__fecha_respuesta__lt=fin,
        )
        .exclude(estado=Pedido.ESTADO_CANCELADO)
        .select_related("solicitud_nomina")
        .prefetch_related(
            "items__producto_presentacion__producto", "items__producto_presentacion__presentacion", "items__combo",
        )
        .order_by("solicitud_nomina__fecha_respuesta", "id")
    )


def _nit(documento):
    digitos = re.sub(r"\D", "", documento or "")
    return int(digitos) if digitos else None


def _origen(item):
    return item.combo if item.combo_id else item.producto_presentacion


def revisar(pedidos):
    revision = Revision()
    con_cuenta = set(CuentaLineaSiigo.objects.values_list("linea", "grupo"))
    sin_cuenta = set()
    for pedido in pedidos:
        problemas = []
        if _nit(pedido.solicitud_nomina.documento) is None:
            problemas.append("el documento del empleado no es numérico")
        for item in pedido.items.all():
            origen = _origen(item)
            partes = partes_codigo_siigo(origen.codigo_siigo) if origen is not None else None
            if partes is None:
                problemas.append(f"«{item.producto_nombre} {item.presentacion}» no tiene código Siigo")
            elif partes[:2] not in con_cuenta:
                sin_cuenta.add(partes[:2])
        if problemas:
            revision.problemas.append((pedido, problemas))
        else:
            revision.pedidos.append(pedido)
    revision.lineas_sin_cuenta = [f"{linea:03d}-{grupo:04d}" for linea, grupo in sorted(sin_cuenta)]
    return revision


def numerar(config, pedidos, numero_inicial):
    """
    Numera los pedidos elegidos (en orden) desde `numero_inicial`, aunque ya tuvieran número:
    el usuario decide qué facturas genera y con qué consecutivo. El "próximo número" del fondo
    queda en el siguiente al último usado. Devuelve los pedidos numerados.
    """
    if not numero_inicial or numero_inicial < 1:
        raise SiigoError("Escribe el número de factura inicial (mayor que cero).")
    with transaction.atomic():
        config = ConfiguracionSiigo.objects.select_for_update().get(pk=config.pk)
        ahora = timezone.now()
        numero = numero_inicial
        for pedido in pedidos:
            Pedido.objects.filter(pk=pedido.pk).update(siigo_numero=numero, siigo_exportado_en=ahora)
            pedido.siigo_numero, pedido.siigo_exportado_en = numero, ahora
            numero += 1
        config.siguiente_numero = numero
        config.save(update_fields=["siguiente_numero"])
    return pedidos


# ------------------------------------------------------------------ archivo

def _texto(valor, ancho=ANCHO_DESCRIPCION):
    return " ".join(str(valor).upper().split())[:ancho].ljust(ancho)


def descripcion_producto(item, origen):
    """
    Nombre como en Siigo: "LECHE BOLSA *900ML", "AREPA RELLENA DE QUESO *80GRS X 10 UNDS".
    Usa el nombre actual del catálogo (si el producto se renombró, sale el nombre nuevo) y une la
    primera cantidad con su unidad (900 ml -> 900ML). Los combos salen con su nombre.
    """
    if item.combo_id:
        return item.combo.nombre if item.combo else item.producto_nombre
    if origen is not None:
        nombre, presentacion = origen.producto.nombre, origen.presentacion.nombre
    else:
        nombre, presentacion = item.producto_nombre, item.presentacion
    presentacion = " ".join(presentacion.split()).lstrip("*")
    # Solo la cantidad inicial se pega a su unidad: "900 ml" -> "900ml", "80GRS X 10 UNDS" no cambia.
    presentacion = re.sub(r"^(\d[\d.,]*)\s+(?=[^\W\d_])", lambda m: m.group(1), presentacion)
    return f"{nombre} *{presentacion}" if presentacion else nombre


def _numero(valor):
    valor = Decimal(valor or 0)
    return int(valor) if valor == valor.to_integral_value() else float(valor)


def _fecha_es(fecha):
    return f"{MESES[fecha.month - 1]} {fecha.day:>2}/{fecha.year}"


def cuentas_por_linea():
    """{(línea, grupo): cuenta de venta} en el formato de 10 dígitos de la factura."""
    return {(c.linea, c.grupo): cuenta_siigo(c.cuenta_venta) for c in CuentaLineaSiigo.objects.all()}


def filas_pedido(pedido, config, cuentas=None):
    """
    Lista de filas (dict columna -> valor) de la factura de un pedido. La cuenta de ingreso sale de
    la tabla de cuentas de venta por línea/grupo (si la línea no está, la del fondo); las demás, del fondo.
    """
    cuentas = cuentas_por_linea() if cuentas is None else cuentas
    solicitud = pedido.solicitud_nomina
    momento = timezone.localtime(solicitud.fecha_respuesta)
    vence = momento.date() + timedelta(days=config.dias_vencimiento)
    comun = {
        "A": config.tipo_comprobante, "B": config.codigo_comprobante, "C": pedido.siigo_numero,
        "G": momento.year, "H": momento.month, "I": momento.day,
        "J": config.vendedor, "K": config.ciudad, "N": config.centro_costo, "O": config.subcentro_costo,
        "P": _nit(solicitud.documento), "Q": config.sucursal,
        "AL": int(momento.strftime("%Y%m%d")), "AM": int(momento.strftime("%H%M%S")),
    }
    sin_producto = {"BS": " " * 3, "BT": " " * 4, "BU": " " * 6, "BV": 0, "BX": 0}

    productos = []
    for item in pedido.items.all():
        origen = _origen(item)
        linea, grupo, codigo = partes_codigo_siigo(origen.codigo_siigo)
        productos.append((item, cuentas.get((linea, grupo)) or config.cuenta_ingreso, {
            "L": config.zona, "R": _texto(descripcion_producto(item, origen)),
            "BS": linea, "BT": grupo, "BU": codigo, "BV": item.cantidad,
            "BX": origen.bodega_siigo or config.bodega, "Y": _numero(item.descuento),
        }))

    filas = []
    for item, venta, producto in productos:
        filas.append({**producto, "D": venta, "E": "C", "F": _numero(item.subtotal),
                      "S": 0, "V": 0, "BO": " ", "CQ": " ", "CW": 0, "CX": 0})
    filas.append({
        **sin_producto, "D": config.cuenta_cartera, "E": "D", "F": _numero(pedido.total), "L": 0,
        "R": _texto(solicitud.nombre_completo), "S": 0, "V": config.forma_pago, "Y": 0, "BO": " ", "CQ": " ",
        "CV": config.comprobante, "CW": pedido.siigo_numero, "CX": 1,
        "CY": vence.year, "CZ": vence.month, "DA": vence.day,
    })
    if pedido.descuento:
        filas.append({
            **sin_producto, "D": config.cuenta_descuento, "E": "D", "F": _numero(pedido.descuento), "L": 0,
            "R": _texto(solicitud.nombre_completo), "S": 0, "V": 0, "Y": 0, "BO": " ", "CQ": " ",
            "CV": " " * 5, "CW": 0, "CX": 0, "CY": " " * 4, "CZ": " " * 2, "DA": " " * 2,
        })
    for item, _, producto in productos:
        venta = _numero(item.subtotal)
        filas.append({**producto, "D": config.cuenta_inventario, "E": "C", "F": 0, "S": venta, "V": 0,
                      "BO": "N", "CQ": " ", "CW": 0, "CX": 0})
        filas.append({**producto, "D": config.cuenta_costo, "E": "D", "F": 0, "S": venta, "V": 0,
                      "BO": "N", "CQ": 0, "CW": 0, "CX": 0})

    for secuencia, fila in enumerate(filas, start=1):
        fila.update(comun, M=secuencia)
    return filas


def generar_xlsx(pedidos, config, desde, hasta):
    """Archivo con el mismo aspecto del modelo de Siigo: encabezado azul, Verdana, bordes y notas."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    linea = Side(style="thin", color="000000")
    borde = Border(left=linea, right=linea, top=linea, bottom=linea)
    azul = PatternFill("solid", fgColor=COLOR_ENCABEZADO)
    normal, negrita = Font(name="Verdana", size=10), Font(name="Verdana", size=10, bold=True)

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Hoja1"
    total_columnas = len(COLUMNAS)
    encabezado = [
        (f"*{config.empresa}*", negrita, Alignment(horizontal="left", vertical="center"), 15),
        ("MODELO PARA LA IMPORTACION DE MOVIMIENTO CONTABLE - MODELO GENERAL", Font(name="Verdana", size=18, bold=True),
         Alignment(horizontal="center", vertical="center", wrap_text=True), 24),
        (f"De :  {_fecha_es(desde)}   A :  {_fecha_es(hasta)}", negrita, Alignment(horizontal="center", vertical="center"), 13.5),
        (None, negrita, Alignment(horizontal="left", vertical="center"), 15),
    ]
    for numero, (texto, fuente, alineacion, alto) in enumerate(encabezado, start=1):
        for columna in range(1, total_columnas + 1):
            celda = hoja.cell(row=numero, column=columna)
            celda.border = borde
            if texto is not None:
                celda.fill = azul
        celda = hoja.cell(row=numero, column=1, value=texto)
        celda.font, celda.alignment = fuente, alineacion
        hoja.merge_cells(start_row=numero, start_column=1, end_row=numero, end_column=total_columnas)
        hoja.row_dimensions[numero].height = alto

    for indice, (letra, titulo, formato, ancho, _) in enumerate(COLUMNAS, start=1):
        celda = hoja.cell(row=5, column=indice, value=titulo)
        celda.font, celda.fill, celda.border, celda.number_format = negrita, azul, borde, formato
        if NOTAS.get(letra):
            celda.comment = Comment(NOTAS[letra], "Siigo", width=260, height=110)
        hoja.column_dimensions[letra].width = ancho

    fila_actual = 6
    cuentas = cuentas_por_linea()
    for pedido in pedidos:
        for datos in filas_pedido(pedido, config, cuentas):
            for indice, (letra, _, formato, _, defecto) in enumerate(COLUMNAS, start=1):
                celda = hoja.cell(row=fila_actual, column=indice, value=datos.get(letra, defecto))
                celda.number_format, celda.font, celda.border = formato, normal, borde
            fila_actual += 1

    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def nombre_archivo(config, desde, hasta):
    nombre = re.sub(r"[^A-Za-z0-9]+", "_", config.fondo.nombre).strip("_").lower() or "fondo"
    return f"siigo_{nombre}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx"
