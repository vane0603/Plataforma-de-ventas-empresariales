"""
Casos de uso del descuento por nómina.

Toda transición de estado de una solicitud pasa por `aplicar_decision`, que es
el único lugar donde se reserva cupo, se actualiza el pedido y se audita.
Las funciones reciben IDs/objetos simples para poder ejecutarse más adelante
desde una cola de tareas (Celery, RQ, etc.) sin cambios.
"""

import csv
import io
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import AfiliadoFondo, HistorialSolicitud, SolicitudDescuentoNomina
from apps.core.cifrado import huella
from apps.notificaciones.models import Notificacion
from apps.notificaciones.services import notificar

from .verificacion import calcular_decision, normalizar_documento, obtener_verificador

logger = logging.getLogger(__name__)


class DecisionInvalida(Exception):
    pass


class SolicitudError(Exception):
    pass


ESTADOS_APROBADOS = (
    SolicitudDescuentoNomina.ESTADO_APROBADA,
    SolicitudDescuentoNomina.ESTADO_APROBADA_PARCIAL,
)


# =====================================================
# CREACIÓN DE LA SOLICITUD
# =====================================================

def crear_solicitud(pedido, form, usuario):
    """
    Crea la solicitud de nómina de un pedido a partir de un SolicitudDescuentoNominaForm
    válido (web o API) y la envía a verificación. Devuelve la solicitud actualizada.
    """
    from apps.pedidos.models import Pedido

    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if pedido.usuario_id != usuario.id or pedido.metodo_pago != Pedido.METODO_NOMINA:
            raise SolicitudError("Este pedido no es de descuento por nómina.")
        if SolicitudDescuentoNomina.objects.filter(pedido=pedido).exists():
            raise SolicitudError("Este pedido ya tiene una solicitud de nómina.")
        if pedido.estado != Pedido.ESTADO_PENDIENTE_SOLICITUD_NOMINA:
            raise SolicitudError("Este pedido no admite una nueva solicitud de nómina.")

        solicitud = form.save(commit=False)
        solicitud.usuario = usuario
        solicitud.pedido = pedido
        solicitud.valor_solicitado = pedido.total
        solicitud.estado = SolicitudDescuentoNomina.ESTADO_PENDIENTE
        solicitud.autorizacion_datos = True
        solicitud.autorizacion_fecha = timezone.now()
        solicitud.autorizacion_version = settings.POLITICA_DATOS_VERSION
        solicitud.save()
        registrar_historial(solicitud, HistorialSolicitud.EVENTO_CREADA, usuario=usuario)

        pedido.estado = Pedido.ESTADO_EN_REVISION_NOMINA
        campos = ["estado", "updated_at"]
        if solicitud.finca_id:
            # Con nómina se entrega en la finca elegida.
            pedido.direccion_entrega = f"Finca {solicitud.finca.nombre}"[:250]
            pedido.ciudad = (solicitud.finca.municipio or pedido.ciudad or "")[:120]
            campos += ["direccion_entrega", "ciudad"]
        pedido.save(update_fields=campos)

    # Fuera de la transacción: puede consultar un servicio externo del fondo.
    return procesar_verificacion(solicitud.id)


# =====================================================
# VERIFICACIÓN Y DECISIÓN
# =====================================================

def registrar_historial(solicitud, evento, usuario=None, **detalle):
    HistorialSolicitud.objects.create(
        solicitud=solicitud,
        evento=evento,
        estado=solicitud.estado,
        usuario=usuario,
        detalle={k: str(v) if isinstance(v, Decimal) else v for k, v in detalle.items()},
    )


def procesar_verificacion(solicitud_id):
    """
    Consulta al fondo (manual, padrón o API) si el solicitante está vinculado y
    su cupo. Si el fondo tiene decisión automática y el resultado es concluyente,
    decide de inmediato; si no, la solicitud queda pendiente para el gestor.

    Se ejecuta FUERA de transacciones porque puede hacer llamadas de red.
    """
    solicitud = (
        SolicitudDescuentoNomina.objects
        .select_related("fondo", "pedido")
        .get(pk=solicitud_id)
    )
    if not solicitud.esta_pendiente:
        return solicitud

    resultado = obtener_verificador(solicitud.fondo).verificar(solicitud)

    solicitud.vinculacion_validada = resultado.vinculado
    solicitud.cupo_disponible_reportado = resultado.cupo_disponible
    solicitud.afiliado = resultado.afiliado
    solicitud.verificacion_mensaje = resultado.mensaje
    if resultado.referencia:
        solicitud.referencia_fondo = resultado.referencia
    solicitud.save(update_fields=[
        "vinculacion_validada",
        "cupo_disponible_reportado",
        "afiliado",
        "verificacion_mensaje",
        "referencia_fondo",
    ])
    registrar_historial(
        solicitud,
        HistorialSolicitud.EVENTO_VERIFICACION,
        modo=solicitud.fondo.modo_verificacion,
        vinculado=resultado.vinculado,
        cupo=resultado.cupo_disponible,
        mensaje=resultado.mensaje,
    )

    if solicitud.fondo.decision_automatica and resultado.concluyente:
        estado, valor = calcular_decision(
            solicitud.valor_solicitado,
            resultado.vinculado,
            resultado.cupo_disponible,
        )
        return aplicar_decision(
            solicitud,
            estado=estado,
            valor_aprobado=valor,
            vinculado=resultado.vinculado,
            cupo_reportado=resultado.cupo_disponible,
            respuesta=resultado.mensaje,
            origen=SolicitudDescuentoNomina.ORIGEN_AUTOMATICO,
        )

    transaction.on_commit(lambda: notificar_fondo_nueva_solicitud(solicitud))
    return solicitud


def aplicar_decision(
    solicitud,
    *,
    estado,
    valor_aprobado,
    vinculado,
    origen,
    cupo_reportado=None,
    referencia="",
    respuesta="",
    usuario=None,
):
    from apps.pedidos.models import Pedido

    S = SolicitudDescuentoNomina
    mapa_pedido = {
        S.ESTADO_APROBADA: Pedido.ESTADO_APROBADO_NOMINA,
        S.ESTADO_APROBADA_PARCIAL: Pedido.ESTADO_APROBADO_PARCIAL,
        S.ESTADO_RECHAZADA: Pedido.ESTADO_RECHAZADO_NOMINA,
    }
    if estado not in mapa_pedido:
        raise DecisionInvalida("Debe registrar una decisión final.")

    with transaction.atomic():
        solicitud = S.objects.select_for_update().get(pk=solicitud.pk)
        if not solicitud.esta_pendiente:
            raise DecisionInvalida("Esta solicitud ya fue decidida.")

        valor_aprobado = valor_aprobado or Decimal("0")

        if solicitud.afiliado_id:
            afiliado = AfiliadoFondo.objects.select_for_update().get(pk=solicitud.afiliado_id)
            if origen == S.ORIGEN_AUTOMATICO:
                # El cupo pudo cambiar desde la verificación: se recalcula con el valor bloqueado.
                cupo_reportado = afiliado.cupo_disponible
                estado, valor_aprobado = calcular_decision(
                    solicitud.valor_solicitado, vinculado, afiliado.cupo_disponible
                )
            if estado in ESTADOS_APROBADOS:
                if valor_aprobado > afiliado.cupo_disponible:
                    raise DecisionInvalida(
                        f"El cupo vigente del afiliado en el padrón es ${afiliado.cupo_disponible:,.0f}."
                    )
                afiliado.cupo_disponible -= valor_aprobado
                afiliado.save(update_fields=["cupo_disponible", "updated_at"])
                solicitud.cupo_reservado = valor_aprobado

        solicitud.estado = estado
        solicitud.valor_aprobado = valor_aprobado if estado in ESTADOS_APROBADOS else Decimal("0")
        solicitud.vinculacion_validada = vinculado
        if cupo_reportado is not None:
            solicitud.cupo_disponible_reportado = cupo_reportado
        if referencia:
            solicitud.referencia_fondo = referencia
        if respuesta:
            solicitud.respuesta_fondo = respuesta
        solicitud.origen_decision = origen
        solicitud.decidido_por = usuario
        solicitud.fecha_respuesta = timezone.now()
        solicitud.save()

        if solicitud.pedido_id:
            Pedido.objects.filter(pk=solicitud.pedido_id).update(
                estado=mapa_pedido[estado],
                valor_nomina=solicitud.valor_aprobado,
                updated_at=timezone.now(),
            )

        registrar_historial(
            solicitud,
            HistorialSolicitud.EVENTO_DECISION,
            usuario=usuario,
            origen=origen,
            valor_aprobado=solicitud.valor_aprobado,
            cupo=solicitud.cupo_disponible_reportado,
        )
        transaction.on_commit(lambda: notificar_usuario_respuesta(solicitud))

    return solicitud


def liberar_cupo(solicitud, usuario=None):
    """Devuelve al padrón el cupo reservado (p. ej. al cancelar el pedido). Idempotente."""
    with transaction.atomic():
        solicitud = SolicitudDescuentoNomina.objects.select_for_update().get(pk=solicitud.pk)
        if not solicitud.cupo_reservado or not solicitud.afiliado_id:
            return solicitud
        afiliado = AfiliadoFondo.objects.select_for_update().get(pk=solicitud.afiliado_id)
        afiliado.cupo_disponible += solicitud.cupo_reservado
        afiliado.save(update_fields=["cupo_disponible", "updated_at"])
        liberado = solicitud.cupo_reservado
        solicitud.cupo_reservado = Decimal("0")
        solicitud.save(update_fields=["cupo_reservado"])
        registrar_historial(
            solicitud, HistorialSolicitud.EVENTO_CUPO_LIBERADO, usuario=usuario, valor=liberado
        )
    return solicitud


# =====================================================
# PADRÓN DE AFILIADOS
# =====================================================

@dataclass
class ResultadoImportacion:
    creados: int = 0
    actualizados: int = 0
    desactivados: int = 0
    errores: list = field(default_factory=list)


def _parse_monto(texto):
    valor = (texto or "").replace("$", "").replace(" ", "").strip()
    if not valor:
        return Decimal("0")
    if "," in valor and "." in valor:
        # Formato colombiano: 1.500.000,50
        valor = valor.replace(".", "").replace(",", ".")
    elif "," in valor:
        entero, _, dec = valor.rpartition(",")
        valor = f"{entero}.{dec}" if len(dec) <= 2 and entero.count(",") == 0 else valor.replace(",", "")
    elif valor.count(".") > 1 or (valor.count(".") == 1 and len(valor.rpartition(".")[2]) == 3):
        valor = valor.replace(".", "")
    monto = Decimal(valor)
    if monto < 0:
        raise InvalidOperation
    return monto


def _parse_activo(texto):
    return (texto or "si").strip().lower() not in {"0", "no", "false", "inactivo", "n"}


def importar_padron(fondo, archivo, desactivar_ausentes=False):
    """
    Carga/actualiza el padrón desde un CSV (separador ',' o ';', UTF-8).
    Columnas: documento, cupo_disponible (obligatorias); nombre, empresa, activo (opcionales).
    Usa operaciones masivas para soportar padrones de miles de afiliados.
    """
    if isinstance(archivo, (bytes, bytearray)):
        archivo = archivo.decode("utf-8-sig")
    if isinstance(archivo, str):
        archivo = io.StringIO(archivo)

    contenido = archivo.read()
    if isinstance(contenido, bytes):
        contenido = contenido.decode("utf-8-sig")
    contenido = contenido.lstrip("﻿")
    primera_linea = contenido.splitlines()[0] if contenido else ""
    delimitador = ";" if primera_linea.count(";") > primera_linea.count(",") else ","
    lector = csv.DictReader(io.StringIO(contenido), delimiter=delimitador)
    lector.fieldnames = [(c or "").strip().lower() for c in (lector.fieldnames or [])]

    resultado = ResultadoImportacion()
    faltantes = {"documento", "cupo_disponible"} - set(lector.fieldnames)
    if faltantes:
        resultado.errores.append(f"Faltan columnas obligatorias: {', '.join(sorted(faltantes))}.")
        return resultado

    filas = {}
    for numero, fila in enumerate(lector, start=2):
        documento = normalizar_documento(fila.get("documento"))
        if not documento:
            resultado.errores.append(f"Fila {numero}: documento vacío.")
            continue
        try:
            cupo = _parse_monto(fila.get("cupo_disponible"))
        except (InvalidOperation, ValueError):
            resultado.errores.append(f"Fila {numero}: cupo inválido '{fila.get('cupo_disponible')}'.")
            continue
        filas[documento] = {
            "nombre": (fila.get("nombre") or "").strip()[:200],
            "empresa": (fila.get("empresa") or "").strip()[:200],
            "cupo_disponible": cupo,
            "activo": _parse_activo(fila.get("activo")),
        }

    with transaction.atomic():
        # Se busca por huella: el documento está cifrado en la base de datos.
        existentes = {
            a.documento_huella: a
            for a in AfiliadoFondo.objects.select_for_update().filter(fondo=fondo)
        }
        nuevos, cambiados = [], []
        for documento, datos in filas.items():
            afiliado = existentes.get(huella(documento))
            if afiliado is None:
                # bulk_create no llama a save(): la huella se asigna aquí.
                nuevos.append(AfiliadoFondo(
                    fondo=fondo, documento=documento, documento_huella=huella(documento), **datos
                ))
            else:
                for campo, valor in datos.items():
                    setattr(afiliado, campo, valor)
                cambiados.append(afiliado)

        AfiliadoFondo.objects.bulk_create(nuevos, batch_size=1000)
        AfiliadoFondo.objects.bulk_update(
            cambiados, ["nombre", "empresa", "cupo_disponible", "activo"], batch_size=1000
        )
        resultado.creados = len(nuevos)
        resultado.actualizados = len(cambiados)

        if desactivar_ausentes and filas:
            resultado.desactivados = (
                AfiliadoFondo.objects
                .filter(fondo=fondo, activo=True)
                .exclude(documento_huella__in=[huella(d) for d in filas])
                .update(activo=False)
            )

    return resultado


# =====================================================
# NOTIFICACIONES
# =====================================================

def _url_absoluta(nombre, *args):
    return settings.PUBLIC_BASE_URL.rstrip("/") + reverse(nombre, args=args)


def notificar_fondo_nueva_solicitud(solicitud):
    """Avisa al correo del fondo y a sus gestores que hay una solicitud por revisar."""
    destinatarios = set(
        solicitud.fondo.gestores
        .filter(is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if solicitud.fondo.correo:
        destinatarios.add(solicitud.fondo.correo)
    if not destinatarios:
        logger.warning("Fondo %s sin destinatarios para la solicitud %s", solicitud.fondo, solicitud.pk)
        return

    mensaje = (
        "Se ha recibido una nueva solicitud de descuento por nómina.\n\n"
        f"Solicitante: {solicitud.nombre_completo}\n"
        f"Documento: {solicitud.documento}\n"
        f"Empresa: {solicitud.empresa}\n"
        f"Valor solicitado: ${solicitud.valor_solicitado:,.0f}\n"
    )
    if solicitud.numero_afiliado:
        mensaje += f"Número de afiliado: {solicitud.numero_afiliado}\n"
    if solicitud.verificacion_mensaje:
        mensaje += f"\nVerificación previa: {solicitud.verificacion_mensaje}\n"
    mensaje += (
        "\nRevise y decida la solicitud en:\n"
        f"{_url_absoluta('fondos:gestion_detalle', solicitud.id)}\n"
    )

    send_mail(
        f"Nueva solicitud de descuento por nómina #{solicitud.id}",
        mensaje,
        settings.DEFAULT_FROM_EMAIL,
        sorted(destinatarios),
        fail_silently=True,
    )


def notificar_usuario_respuesta(solicitud):
    S = SolicitudDescuentoNomina
    evento = {
        S.ESTADO_APROBADA: Notificacion.EVENTO_NOMINA_APROBADA,
        S.ESTADO_APROBADA_PARCIAL: Notificacion.EVENTO_NOMINA_PARCIAL,
        S.ESTADO_RECHAZADA: Notificacion.EVENTO_NOMINA_RECHAZADA,
    }.get(solicitud.estado)
    if evento:
        notificar(evento, solicitud=solicitud)
