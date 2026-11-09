"""
Importa la tabla de líneas de Siigo (Excel) a "Cuentas por línea Siigo".

El archivo puede tener filas de título arriba: se busca la fila de encabezados que tenga
LINEA y GRUPO. Columnas usadas: LINEA, GRUPO, CTA VENTA, CTA INVENT, CTA COSTOS y NOMBRE LINEA
(las demás se ignoran). CTA INVENT y CTA COSTOS son opcionales.
"""

import unicodedata
from dataclasses import dataclass, field

from django.db import transaction

from .models import CuentaLineaSiigo

COLUMNAS = {
    "LINEA": "linea",
    "GRUPO": "grupo",
    "CTA VENTA": "cuenta_venta",
    "CTA INVENT": "cuenta_inventario",
    "CTA COSTOS": "cuenta_costo",
    "NOMBRE LINEA": "nombre_linea",
}
OBLIGATORIAS = ("linea", "grupo", "cuenta_venta")


class ImportacionError(Exception):
    pass


@dataclass
class Resultado:
    creadas: int = 0
    actualizadas: int = 0
    errores: list = field(default_factory=list)


def _normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(texto.upper().replace(".", " ").split())


def _digitos(valor):
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return "".join(c for c in str(valor if valor is not None else "") if c.isdigit())


def _cuenta_opcional(valor):
    """Una cuenta en ceros (00000000) o vacía cuenta como no informada."""
    digitos = _digitos(valor)[:10]
    return digitos if digitos.strip("0") else ""


def importar_cuentas_lineas(archivo):
    from openpyxl import load_workbook

    try:
        hoja = load_workbook(archivo, read_only=True, data_only=True).active
    except Exception:
        raise ImportacionError("No se pudo leer el archivo. Súbelo en formato Excel (.xlsx).")

    filas = hoja.iter_rows(values_only=True)
    posiciones = None
    for fila in filas:
        titulos = [_normalizar(valor) for valor in fila]
        if "LINEA" in titulos and "GRUPO" in titulos:
            posiciones = {COLUMNAS[t]: i for i, t in enumerate(titulos) if t in COLUMNAS}
            break
    faltan = [c for c in OBLIGATORIAS if posiciones is None or c not in posiciones]
    if faltan:
        raise ImportacionError(
            "No se encontraron las columnas LINEA, GRUPO y CTA VENTA en el archivo."
        )

    resultado = Resultado()
    with transaction.atomic():
        for numero, fila in enumerate(filas, start=2):
            datos = {campo: (fila[i] if i < len(fila) else None) for campo, i in posiciones.items()}
            linea, grupo = _digitos(datos["linea"]), _digitos(datos["grupo"])
            if not linea and not grupo:
                continue
            venta = _digitos(datos.get("cuenta_venta"))[:10]
            if not linea or not grupo or not venta.strip("0"):
                resultado.errores.append(f"Fila con línea «{datos['linea']}» y grupo «{datos['grupo']}»: faltan datos.")
                continue
            _, creada = CuentaLineaSiigo.objects.update_or_create(
                linea=int(linea), grupo=int(grupo),
                defaults={
                    "cuenta_venta": venta,
                    "cuenta_inventario": _cuenta_opcional(datos.get("cuenta_inventario")),
                    "cuenta_costo": _cuenta_opcional(datos.get("cuenta_costo")),
                    "nombre_linea": str(datos.get("nombre_linea") or "").strip()[:100],
                },
            )
            if creada:
                resultado.creadas += 1
            else:
                resultado.actualizadas += 1
    return resultado
