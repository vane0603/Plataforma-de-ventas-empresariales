from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("productos", "0003_producto_almacenamiento_producto_caracteristicas_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Carrito",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(blank=True, max_length=100, null=True)),
                ("activo", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("usuario", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="carritos", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Carrito", "verbose_name_plural": "Carritos"},
        ),
        migrations.CreateModel(
            name="CarritoItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cantidad", models.PositiveIntegerField(default=1)),
                ("precio_unitario", models.DecimalField(decimal_places=2, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("carrito", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="carrito.carrito")),
                ("presentacion", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items_carrito", to="productos.productopresentacion")),
            ],
            options={"verbose_name": "Producto del carrito", "verbose_name_plural": "Productos del carrito"},
        ),
        migrations.AddConstraint(
            model_name="carrito",
            constraint=models.UniqueConstraint(condition=models.Q(("activo", True), ("usuario__isnull", False)), fields=("usuario",), name="unico_carrito_usuario_activo"),
        ),
        migrations.AddConstraint(
            model_name="carrito",
            constraint=models.UniqueConstraint(condition=models.Q(("activo", True), ("session_key__isnull", False)), fields=("session_key",), name="unico_carrito_session_activo"),
        ),
        migrations.AddConstraint(
            model_name="carritoitem",
            constraint=models.UniqueConstraint(fields=("carrito", "presentacion"), name="una_presentacion_por_carrito"),
        ),
    ]
