"""
Reintenta los avisos que fallaron (correo caído, WhatsApp sin conexión...).

Programar cada 15-30 minutos (Programador de tareas de Windows o cron):
    python manage.py reenviar_notificaciones
"""

from django.core.management.base import BaseCommand

from apps.notificaciones.services import MAXIMO_INTENTOS, reenviar_fallidas


class Command(BaseCommand):
    help = "Reintenta el envío de las notificaciones fallidas recientes."

    def add_arguments(self, parser):
        parser.add_argument("--horas", type=int, default=72, help="Antigüedad máxima en horas (por defecto 72).")
        parser.add_argument(
            "--intentos", type=int, default=MAXIMO_INTENTOS,
            help=f"Intentos máximos por aviso (por defecto {MAXIMO_INTENTOS}).",
        )

    def handle(self, *args, horas, intentos, **opciones):
        enviadas, fallidas = reenviar_fallidas(horas=horas, maximo_intentos=intentos)
        self.stdout.write(self.style.SUCCESS(f"Reenviadas: {enviadas}. Siguen fallando: {fallidas}."))
