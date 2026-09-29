from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def copiar_datos_afiliado(apps, schema_editor):
    Solicitud = apps.get_model("fondos", "SolicitudDescuentoNomina")
    for solicitud in Solicitud.objects.select_related("afiliado__usuario", "afiliado__fondo").all():
        afiliado = solicitud.afiliado
        usuario = afiliado.usuario
        solicitud.usuario_id = usuario.id
        solicitud.fondo_id = afiliado.fondo_id
        solicitud.nombre_completo = usuario.get_full_name() or usuario.get_username()
        solicitud.documento = afiliado.documento
        solicitud.correo = usuario.email or ""
        solicitud.numero_afiliado = afiliado.numero_afiliado or ""
        solicitud.save(update_fields=[
            "usuario", "fondo", "nombre_completo", "documento", "correo", "numero_afiliado"
        ])


class Migration(migrations.Migration):
    dependencies = [
        ("fondos", "0003_solicituddescuentonomina"),
        ("pedidos", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="fondoempleado",
            name="gestores",
            field=models.ManyToManyField(blank=True, help_text="Usuarios autorizados para revisar solicitudes de este fondo.", related_name="fondos_gestionados", to=settings.AUTH_USER_MODEL),
        ),
        migrations.RenameField(model_name="solicituddescuentonomina", old_name="observaciones", new_name="observaciones_usuario"),
        migrations.RenameField(model_name="solicituddescuentonomina", old_name="respuesta", new_name="respuesta_fondo"),
        migrations.AddField(model_name="solicituddescuentonomina", name="usuario", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="solicitudes_nomina", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="solicituddescuentonomina", name="fondo", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="solicitudes", to="fondos.fondoempleado")),
        migrations.AddField(model_name="solicituddescuentonomina", name="pedido", field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="solicitud_nomina", to="pedidos.pedido")),
        migrations.AddField(model_name="solicituddescuentonomina", name="nombre_completo", field=models.CharField(default="", max_length=200)),
        migrations.AddField(model_name="solicituddescuentonomina", name="documento", field=models.CharField(default="", max_length=50)),
        migrations.AddField(model_name="solicituddescuentonomina", name="telefono", field=models.CharField(blank=True, max_length=50)),
        migrations.AddField(model_name="solicituddescuentonomina", name="correo", field=models.EmailField(blank=True, max_length=254)),
        migrations.AddField(model_name="solicituddescuentonomina", name="empresa", field=models.CharField(default="Tío Campo", max_length=200)),
        migrations.AddField(model_name="solicituddescuentonomina", name="numero_afiliado", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="solicituddescuentonomina", name="vinculacion_validada", field=models.BooleanField(blank=True, null=True, verbose_name="¿Trabaja/está afiliado con la entidad?")),
        migrations.AddField(model_name="solicituddescuentonomina", name="valor_aprobado", field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name="solicituddescuentonomina", name="cupo_disponible_reportado", field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name="solicituddescuentonomina", name="referencia_fondo", field=models.CharField(blank=True, max_length=100)),
        migrations.RunPython(copiar_datos_afiliado, migrations.RunPython.noop),
        migrations.RemoveField(model_name="solicituddescuentonomina", name="afiliado"),
        migrations.AlterField(model_name="solicituddescuentonomina", name="usuario", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="solicitudes_nomina", to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name="solicituddescuentonomina", name="fondo", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="solicitudes", to="fondos.fondoempleado")),
        migrations.AlterField(model_name="solicituddescuentonomina", name="nombre_completo", field=models.CharField(max_length=200)),
        migrations.AlterField(model_name="solicituddescuentonomina", name="documento", field=models.CharField(max_length=50)),
        migrations.AlterField(model_name="solicituddescuentonomina", name="estado", field=models.CharField(choices=[("PENDIENTE", "Pendiente"), ("APROBADA", "Aprobada"), ("APROBADA_PARCIAL", "Aprobada parcialmente"), ("RECHAZADA", "Rechazada")], default="PENDIENTE", max_length=20)),
        migrations.DeleteModel(name="AfiliadoFondo"),
    ]
