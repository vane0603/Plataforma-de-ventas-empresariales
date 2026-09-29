from django.db import models


class Combo(models.Model):

    codigo = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Código",
    )

    nombre = models.CharField(
        max_length=200,
        verbose_name="Nombre",
    )

    descripcion = models.TextField(
        blank=True,
        verbose_name="Descripción",
    )

    imagen = models.ImageField(
        upload_to="combos/",
        blank=True,
        null=True,
        verbose_name="Imagen",
    )

    precio = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Precio",
    )

    precio_anterior = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name="Precio anterior",
    )

    stock = models.PositiveIntegerField(
        default=0,
        verbose_name="Stock",
    )

    destacado = models.BooleanField(
        default=False,
        verbose_name="Destacado",
    )

    activo = models.BooleanField(
        default=True,
        verbose_name="Activo",
    )

    orden = models.PositiveIntegerField(
        default=0,
        verbose_name="Orden",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Combo"
        verbose_name_plural = "Combos"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"