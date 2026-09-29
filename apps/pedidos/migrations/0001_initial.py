from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("carrito", "0001_initial"),
        ("productos", "0003_producto_almacenamiento_producto_caracteristicas_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Pedido",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("numero", models.CharField(editable=False, max_length=40, unique=True)),
                ("metodo_pago", models.CharField(choices=[("ELECTRONICO", "Pago electrónico"), ("OTRO", "Otro medio de pago"), ("NOMINA", "Descuento por nómina")], max_length=20)),
                ("estado", models.CharField(choices=[("PENDIENTE_PAGO", "Pendiente de pago"), ("PEND_SOL_NOMINA", "Pendiente de solicitud de nómina"), ("REVISION_NOMINA", "En revisión por el fondo"), ("APROBADO_NOMINA", "Aprobado por nómina"), ("APROBADO_PARCIAL", "Aprobado parcialmente"), ("RECHAZADO_NOMINA", "Rechazado por el fondo"), ("PAGADO", "Pagado"), ("CANCELADO", "Cancelado")], default="PENDIENTE_PAGO", max_length=30)),
                ("subtotal", models.DecimalField(decimal_places=2, max_digits=12)),
                ("total", models.DecimalField(decimal_places=2, max_digits=12)),
                ("direccion_entrega", models.CharField(max_length=250)),
                ("ciudad", models.CharField(max_length=120)),
                ("observaciones", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("carrito", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="pedido", to="carrito.carrito")),
                ("usuario", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pedidos", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Pedido", "verbose_name_plural": "Pedidos", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="PedidoItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("producto_nombre", models.CharField(max_length=200)),
                ("referencia", models.CharField(max_length=50)),
                ("presentacion", models.CharField(max_length=150)),
                ("cantidad", models.PositiveIntegerField()),
                ("precio_unitario", models.DecimalField(decimal_places=2, max_digits=12)),
                ("subtotal", models.DecimalField(decimal_places=2, max_digits=12)),
                ("pedido", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="pedidos.pedido")),
                ("producto_presentacion", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="items_pedido", to="productos.productopresentacion")),
            ],
            options={"verbose_name": "Ítem de pedido", "verbose_name_plural": "Ítems de pedido", "ordering": ["id"]},
        ),
    ]
