"""Código de producto de Siigo: línea-grupo-código (por ejemplo 702-15-45)."""

from django.core.validators import RegexValidator

validar_codigo_siigo = RegexValidator(
    r"^\d{1,3}-\d{1,4}-\d{1,6}$",
    "Usa el formato línea-grupo-código de Siigo, por ejemplo 702-15-45.",
)

AYUDA_CODIGO = "Línea-grupo-código del producto en Siigo, por ejemplo 702-15-45. Necesario para exportar a Siigo."
AYUDA_BODEGA = "Código de la bodega en Siigo. Vacío = la bodega por defecto del fondo."


def partes_codigo_siigo(codigo):
    """'702-15-45' -> (702, 15, 45); None si está vacío o mal escrito."""
    try:
        validar_codigo_siigo(codigo or "")
    except Exception:
        return None
    return tuple(int(parte) for parte in codigo.split("-"))
