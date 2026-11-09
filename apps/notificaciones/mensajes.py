"""
Contenido de cada aviso. Un mismo `Mensaje` alimenta todos los canales:
el correo usa título, párrafos, detalle y botón; WhatsApp usa una plantilla
aprobada por Meta con parámetros ({{1}}, {{2}}, ...).
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import Notificacion as N


@dataclass
class Mensaje:
    asunto: str
    titulo: str
    saludo: str
    parrafos: list = field(default_factory=list)
    detalle: list = field(default_factory=list)       # [(etiqueta, valor)]
    items: list = field(default_factory=list)         # líneas del pedido
    nota: str = ""
    boton_texto: str = ""
    boton_url: str = ""
    # WhatsApp: nombre de la plantilla en Meta y sus parámetros en orden.
    plantilla: str = ""
    parametros: list = field(default_factory=list)


# Nombres de las plantillas que se deben crear en WhatsApp Manager (ver LEEME).
PLANTILLAS_WHATSAPP = {
    N.EVENTO_PEDIDO_CREADO: "tio_pedido_recibido",
    N.EVENTO_NOMINA_APROBADA: "tio_nomina_aprobada",
    N.EVENTO_NOMINA_PARCIAL: "tio_nomina_parcial",
    N.EVENTO_NOMINA_RECHAZADA: "tio_nomina_rechazada",
    N.EVENTO_PAGO_APROBADO: "tio_pago_aprobado",
    N.EVENTO_PEDIDO_DESPACHADO: "tio_pedido_en_camino",
    N.EVENTO_PEDIDO_ENTREGADO: "tio_pedido_entregado",
}
# El despacho de un pedido que se recoge en tienda usa otra plantilla.
PLANTILLA_LISTO_RECOGER = "tio_pedido_listo_recoger"


def pesos(valor):
    return "$" + f"{valor or 0:,.0f}".replace(",", ".")


def url_absoluta(nombre, *args):
    return settings.PUBLIC_BASE_URL.rstrip("/") + reverse(nombre, args=args)


def enlace_pedido(pedido):
    # El enlace con código secreto sirve a invitados y a usuarios sin iniciar sesión.
    return url_absoluta("pedidos:seguimiento", pedido.codigo_acceso)


def punto_entrega(pedido):
    solicitud = getattr(pedido, "solicitud_nomina", None)
    if solicitud is not None and solicitud.finca_id:
        return f"{solicitud.finca} ({solicitud.fondo.nombre})"
    if pedido.recoge_en_tienda and pedido.punto_recogida_id:
        return f"{pedido.punto_recogida.nombre} ({pedido.punto_recogida.ubicacion})"
    return ", ".join(p for p in (pedido.direccion_entrega, pedido.ciudad) if p)


def nombre_destinatario(notificacion):
    pedido, solicitud = notificacion.pedido, notificacion.solicitud
    if solicitud is not None:
        return solicitud.nombre_completo
    return pedido.nombre_cliente if pedido else "cliente"


# ----------------------------------------------------------------- eventos

def _pedido_creado(n, nombre):
    pedido = n.pedido
    if pedido.metodo_pago == pedido.METODO_NOMINA:
        aviso = "La fecha de entrega se acuerda con tu fondo de empleados."
    elif pedido.recoge_en_tienda:
        aviso = f"Lo recoges en {punto_entrega(pedido)}. Te avisaremos cuando esté listo."
    else:
        aviso = "Te contactaremos para coordinar la entrega."
    return Mensaje(
        asunto=f"Recibimos tu pedido {pedido.numero}",
        titulo="¡Recibimos tu pedido!",
        saludo=f"Hola {nombre},",
        parrafos=[f"Recibimos tu pedido {pedido.numero}.", aviso],
        items=[
            f"{item.cantidad} x {item.producto_nombre} ({item.presentacion}): {pesos(item.subtotal)}"
            for item in pedido.items.all()
        ],
        detalle=[("Total", pesos(pedido.total)), ("Medio de pago", pedido.get_metodo_pago_display())],
        boton_texto="Consulta tu pedido aquí",
        boton_url=enlace_pedido(pedido),
        parametros=[nombre, pedido.numero, pesos(pedido.total)],
    )


def _respuesta_nomina(n, nombre):
    solicitud = n.solicitud
    pedido = solicitud.pedido if solicitud.pedido_id else None
    referencia = pedido.numero if pedido else f"#{solicitud.id}"
    saldo = solicitud.valor_solicitado - (solicitud.valor_aprobado or 0)

    detalle = [
        ("Resultado", solicitud.get_estado_display()),
        ("Valor solicitado", pesos(solicitud.valor_solicitado)),
        ("Valor aprobado", pesos(solicitud.valor_aprobado)),
    ]
    if n.evento == N.EVENTO_NOMINA_APROBADA:
        titulo = "Tu fondo aprobó el descuento por nómina"
        nota = "La fecha de entrega se acuerda con tu fondo de empleados."
        parametros = [nombre, referencia, pesos(solicitud.valor_aprobado)]
    elif n.evento == N.EVENTO_NOMINA_PARCIAL:
        titulo = "Tu fondo aprobó parte del descuento"
        detalle.append(("Saldo por pagar", pesos(saldo)))
        nota = (
            f"Queda un saldo de {pesos(saldo)}. Puedes pagarlo con otro medio "
            "o cancelar el pedido desde la plataforma."
        )
        parametros = [nombre, referencia, pesos(solicitud.valor_aprobado), pesos(saldo)]
    else:
        titulo = "Tu fondo no aprobó el descuento"
        nota = "Puedes pagar el pedido con otro medio de pago o cancelarlo desde la plataforma."
        parametros = [nombre, referencia]

    parrafos = [f"Tu solicitud de descuento por nómina #{solicitud.id} fue respondida."]
    if solicitud.respuesta_fondo:
        parrafos.append(f"Respuesta del fondo: {solicitud.respuesta_fondo}")

    return Mensaje(
        asunto=f"Respuesta a tu solicitud de nómina #{solicitud.id}",
        titulo=titulo,
        saludo=f"Hola {nombre},",
        parrafos=parrafos,
        detalle=detalle,
        nota=nota,
        boton_texto="Ver mi pedido" if pedido else "Ver mi solicitud",
        boton_url=enlace_pedido(pedido) if pedido else url_absoluta("fondos:detalle_solicitud", solicitud.id),
        parametros=parametros,
    )


def _pago_aprobado(n, nombre):
    pedido = n.pedido
    monto = Decimal(n.extra.get("monto") or pedido.total)
    referencia = n.extra.get("referencia", "")
    detalle = [("Valor pagado", pesos(monto))]
    if referencia:
        detalle.append(("Referencia", referencia))
    return Mensaje(
        asunto=f"Pago aprobado - pedido {pedido.numero}",
        titulo="Recibimos tu pago",
        saludo=f"Hola {nombre},",
        parrafos=[f"Recibimos tu pago de {pesos(monto)} para el pedido {pedido.numero}."],
        detalle=detalle,
        boton_texto="Ver mi pedido",
        boton_url=enlace_pedido(pedido),
        parametros=[nombre, pesos(monto), pedido.numero],
    )


def _pedido_listo_para_recoger(pedido, nombre):
    punto = pedido.punto_recogida
    detalle = [("Dónde", f"{punto.nombre} - {punto.ubicacion}")]
    if punto.horario:
        detalle.append(("Horario", punto.horario))
    notas = []
    if pedido.estado == pedido.ESTADO_PENDIENTE_PAGO:
        notas.append(f"Ten listo el pago de {pesos(pedido.saldo_pendiente)} al recoger.")
    if punto.indicaciones:
        notas.append(punto.indicaciones)
    return Mensaje(
        asunto=f"Tu pedido {pedido.numero} está listo para recoger",
        titulo="¡Tu pedido está listo para recoger!",
        saludo=f"Hola {nombre},",
        parrafos=[f"Ya puedes recoger tu pedido {pedido.numero}. Presenta el número del pedido al reclamarlo."],
        detalle=detalle,
        nota=" ".join(notas),
        boton_texto="Ver mi pedido",
        boton_url=enlace_pedido(pedido),
        plantilla=PLANTILLA_LISTO_RECOGER,
        parametros=[nombre, pedido.numero, punto_entrega(pedido)],
    )


def _pedido_despachado(n, nombre):
    pedido = n.pedido
    if pedido.recoge_en_tienda and pedido.punto_recogida_id:
        return _pedido_listo_para_recoger(pedido, nombre)
    punto = punto_entrega(pedido)
    nota = ""
    if pedido.estado == pedido.ESTADO_PENDIENTE_PAGO:
        nota = f"Ten listo el pago de {pesos(pedido.saldo_pendiente)} al recibir."
    elif pedido.requiere_firma:
        nota = "Al recibirlo firmarás en pantalla como soporte del descuento por nómina."
    return Mensaje(
        asunto=f"Tu pedido {pedido.numero} va en camino",
        titulo="¡Tu pedido va en camino!",
        saludo=f"Hola {nombre},",
        parrafos=[f"Tu pedido {pedido.numero} salió para entrega."],
        detalle=[("Punto de entrega", punto)] if punto else [],
        nota=nota,
        boton_texto="Seguir mi pedido",
        boton_url=enlace_pedido(pedido),
        parametros=[nombre, pedido.numero, punto or "la dirección registrada"],
    )


def _pedido_entregado(n, nombre):
    pedido = n.pedido
    entrega = pedido.entrega
    fecha = timezone.localtime(entrega.entregado_en)
    return Mensaje(
        asunto=f"Tu pedido {pedido.numero} fue entregado",
        titulo="Pedido entregado",
        saludo=f"Hola {nombre},",
        parrafos=[
            f"Tu pedido {pedido.numero} fue entregado el {fecha:%d/%m/%Y a las %H:%M} "
            f"y lo recibió {entrega.recibido_por}."
        ],
        boton_texto="Ver la constancia de entrega",
        boton_url=enlace_pedido(pedido),
        parametros=[nombre, pedido.numero, f"{fecha:%d/%m/%Y %H:%M}"],
    )


CONSTRUCTORES = {
    N.EVENTO_PEDIDO_CREADO: _pedido_creado,
    N.EVENTO_NOMINA_APROBADA: _respuesta_nomina,
    N.EVENTO_NOMINA_PARCIAL: _respuesta_nomina,
    N.EVENTO_NOMINA_RECHAZADA: _respuesta_nomina,
    N.EVENTO_PAGO_APROBADO: _pago_aprobado,
    N.EVENTO_PEDIDO_DESPACHADO: _pedido_despachado,
    N.EVENTO_PEDIDO_ENTREGADO: _pedido_entregado,
}


def construir_mensaje(notificacion):
    mensaje = CONSTRUCTORES[notificacion.evento](notificacion, nombre_destinatario(notificacion))
    mensaje.plantilla = mensaje.plantilla or PLANTILLAS_WHATSAPP[notificacion.evento]
    return mensaje
