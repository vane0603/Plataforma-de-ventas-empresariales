"""
Política de retención (Ley 1581 de 2012, principio de finalidad y temporalidad):
borra los datos personales de solicitudes de nómina y pedidos ya cerrados que
superan RETENCION_DATOS_DIAS. Conserva valores, estados y fechas, que son
soporte contable.

Programar una vez al día (Programador de tareas de Windows o cron):
    python manage.py anonimizar_datos
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.fondos.models import AfiliadoFondo, SolicitudDescuentoNomina
from apps.notificaciones.models import Notificacion
from apps.pedidos.models import Pedido

TEXTO_ANONIMO = "Titular anonimizado"

# Pedidos que ya no requieren contactar al comprador.
ESTADOS_PEDIDO_CERRADOS = (
    Pedido.ESTADO_PAGADO,
    Pedido.ESTADO_CANCELADO,
    Pedido.ESTADO_APROBADO_NOMINA,
    Pedido.ESTADO_RECHAZADO_NOMINA,
    Pedido.ESTADO_ENTREGADO,
)


class Command(BaseCommand):
    help = "Anonimiza los datos personales que superan el plazo de retención."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias", type=int, default=None,
            help=f"Plazo en días (por defecto RETENCION_DATOS_DIAS = {settings.RETENCION_DATOS_DIAS}).",
        )
        parser.add_argument("--simular", action="store_true", help="Solo cuenta, no modifica nada.")

    def handle(self, *args, dias=None, simular=False, **opciones):
        dias = dias if dias is not None else settings.RETENCION_DATOS_DIAS
        limite = timezone.now() - timedelta(days=dias)
        ahora = timezone.now()

        solicitudes = SolicitudDescuentoNomina.objects.filter(
            anonimizada_en__isnull=True,
            fecha_respuesta__lt=limite,
        ).exclude(estado=SolicitudDescuentoNomina.ESTADO_PENDIENTE)

        pedidos = Pedido.objects.filter(
            anonimizado_en__isnull=True,
            created_at__lt=limite,
            estado__in=ESTADOS_PEDIDO_CERRADOS,
        )

        # Afiliados que el fondo ya dio de baja y no se actualizan hace más del plazo.
        afiliados = AfiliadoFondo.objects.filter(activo=False, updated_at__lt=limite)

        from apps.pedidos.models import Entrega

        entregas = Entrega.objects.filter(pedido__in=pedidos)
        conteo = (solicitudes.count(), pedidos.count(), afiliados.count())
        if simular:
            self.stdout.write(
                f"[Simulación] Se anonimizarían {conteo[0]} solicitudes y {conteo[1]} pedidos, "
                f"y se eliminarían {conteo[2]} afiliados inactivos (plazo: {dias} días)."
            )
            return

        with transaction.atomic():
            for entrega in entregas.exclude(firma=""):
                entrega.firma.delete(save=False)
            entregas.update(recibido_por=TEXTO_ANONIMO, firma="", observaciones="")
            # Antes de marcar pedidos y solicitudes (el filtro depende de que sigan sin anonimizar).
            Notificacion.objects.filter(Q(pedido__in=pedidos) | Q(solicitud__in=solicitudes)).update(destino="")
            solicitudes.update(
                nombre_completo=TEXTO_ANONIMO,
                documento="",
                documento_huella="",
                telefono="",
                correo="",
                numero_afiliado="",
                observaciones_usuario="",
                anonimizada_en=ahora,
            )
            pedidos.update(
                nombre_contacto="",
                correo_contacto="",
                telefono_contacto="",
                direccion_entrega="Anonimizada",
                observaciones="",
                anonimizado_en=ahora,
            )
            afiliados.delete()

        self.stdout.write(self.style.SUCCESS(
            f"Anonimizadas {conteo[0]} solicitudes y {conteo[1]} pedidos; "
            f"eliminados {conteo[2]} afiliados inactivos (plazo: {dias} días)."
        ))
