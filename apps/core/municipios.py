"""
Departamentos y municipios de Colombia (DIVIPOLA del DANE).

Los datos están en data/municipios_colombia.json; para actualizarlos ver
_herramientas/generar_municipios.py.
"""

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

ARCHIVO = Path(__file__).resolve().parent / "data" / "municipios_colombia.json"

DEPARTAMENTO_POR_DEFECTO = "Bogotá, D.C."
MUNICIPIO_POR_DEFECTO = "Bogotá, D.C."


class MunicipioInvalido(ValueError):
    pass


def normalizar(texto):
    """'  BOGOTÁ, D.C. ' -> 'bogota'. Sin tildes, minúsculas y sin el sufijo D.C."""
    texto = unicodedata.normalize("NFD", (texto or "").lower()).encode("ascii", "ignore").decode()
    texto = texto.replace(", d.c.", "").replace(" d.c.", "")
    return " ".join(texto.replace(",", " ").split())


@lru_cache(maxsize=1)
def datos():
    with open(ARCHIVO, encoding="utf-8") as archivo:
        return json.load(archivo)


def departamentos():
    """[{"nombre": "Antioquia", "municipios": ["Abejorral", ...]}, ...] para las listas desplegables."""
    return [
        {"nombre": dep["nombre"], "municipios": [nombre for _codigo, nombre in dep["municipios"]]}
        for dep in datos()["departamentos"]
    ]


@lru_cache(maxsize=1)
def _indice():
    """normalizado(municipio) -> [(departamento, municipio)] para buscar sin importar tildes."""
    indice = {}
    for dep in datos()["departamentos"]:
        for _codigo, municipio in dep["municipios"]:
            indice.setdefault(normalizar(municipio), []).append((dep["nombre"], municipio))
    return indice


def buscar(municipio, departamento=""):
    """
    Devuelve (departamento, municipio) con los nombres oficiales.
    Sin departamento acepta el nombre si no se repite en el país (p. ej. "Bogotá").
    """
    opciones = _indice().get(normalizar(municipio), [])
    if departamento:
        opciones = [o for o in opciones if normalizar(o[0]) == normalizar(departamento)]
    if not opciones:
        raise MunicipioInvalido("Selecciona un municipio de la lista.")
    if len(opciones) > 1:
        raise MunicipioInvalido("Hay varios municipios con ese nombre: selecciona también el departamento.")
    return opciones[0]


def etiqueta(departamento, municipio):
    """Texto que se guarda en el pedido: 'Madrid, Cundinamarca' o 'Bogotá, D.C.'."""
    return municipio if municipio == departamento else f"{municipio}, {departamento}"
