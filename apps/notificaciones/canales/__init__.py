"""
Registro de canales de notificación. Para agregar otro (SMS, Telegram...):
crear un módulo con una subclase de `Canal` decorada con @registrar("CODIGO")
e importarlo al final de este archivo.
"""

_REGISTRO = {}


class ErrorEnvio(Exception):
    pass


class Canal:
    codigo = ""

    @classmethod
    def habilitado(cls):
        return True

    def destino(self, notificacion):
        """Correo o celular al que se envía; vacío si el comprador no tiene o no autorizó."""
        raise NotImplementedError

    def enviar(self, destino, mensaje):
        """Envía y devuelve el identificador externo (o ""). Lanza ErrorEnvio si falla."""
        raise NotImplementedError


def registrar(codigo):
    def decorador(cls):
        cls.codigo = codigo
        _REGISTRO[codigo] = cls
        return cls

    return decorador


def canales_activos():
    return [cls() for cls in _REGISTRO.values() if cls.habilitado()]


def obtener_canal(codigo):
    try:
        return _REGISTRO[codigo]()
    except KeyError:
        raise LookupError(f"Canal de notificación '{codigo}' no registrado.")


from . import correo, whatsapp  # noqa: E402,F401  (registra los canales)
