from django.db import models


class Categoria(models.Model):
    nombre = models.CharField(
        max_length=100,
        unique=True
    )

    descripcion = models.TextField(
        blank=True
    )

    activo = models.BooleanField(
        default=True
    )

    orden = models.PositiveIntegerField(
        default=0
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class Marca(models.Model):
    nombre = models.CharField(
        max_length=100,
        unique=True
    )

    descripcion = models.TextField(
        blank=True
    )

    activo = models.BooleanField(
        default=True
    )

    class Meta:
        verbose_name = "Marca"
        verbose_name_plural = "Marcas"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class UnidadMedida(models.Model):
    nombre = models.CharField(
        max_length=100
    )

    abreviatura = models.CharField(
        max_length=20
    )

    activo = models.BooleanField(
        default=True
    )

    class Meta:
        verbose_name = "Unidad de medida"
        verbose_name_plural = "Unidades de medida"
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.abreviatura})"


class Presentacion(models.Model):
    nombre = models.CharField(
        max_length=100
    )

    cantidad = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    unidad = models.ForeignKey(
        UnidadMedida,
        on_delete=models.PROTECT,
        related_name="presentaciones"
    )

    activo = models.BooleanField(
        default=True
    )

    class Meta:
        verbose_name = "Presentación"
        verbose_name_plural = "Presentaciones"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre