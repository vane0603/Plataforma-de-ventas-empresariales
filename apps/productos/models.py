from django.db import models

from apps.catalogos.models import (
    Categoria,
    Marca,
    Presentacion,
)


class Producto(models.Model):

    codigo = models.CharField(
        max_length=50,
        unique=True
    )

    nombre = models.CharField(
        max_length=200
    )

    descripcion = models.TextField(
        blank=True
    )

    tipo_producto = models.CharField(
        max_length=200,
        blank=True
    )

    caracteristicas = models.TextField(
        blank=True
    )

    usos_recomendados = models.TextField(
        blank=True
    )

    almacenamiento = models.TextField(
        blank=True
    )

    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name="productos"
    )

    marca = models.ForeignKey(
        Marca,
        on_delete=models.PROTECT,
        related_name="productos"
    )

    imagen = models.ImageField(
        upload_to="productos/",
        blank=True,
        null=True
    )

    destacado = models.BooleanField(
        default=False
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
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class ProductoPresentacion(models.Model):

    producto = models.ForeignKey(
        Producto,
        on_delete=models.CASCADE,
        related_name="presentaciones"
    )

    codigo = models.CharField(
        max_length=50,
        unique=True
    )

    presentacion = models.ForeignKey(
        Presentacion,
        on_delete=models.PROTECT,
        related_name="productos_presentacion"
    )

    precio = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    activo = models.BooleanField(
        default=True
    )

    destacado = models.BooleanField(
        default=False
    )

    orden = models.PositiveIntegerField(
        default=0
    )

    class Meta:
        verbose_name = "Presentación del producto"
        verbose_name_plural = "Presentaciones de productos"
        ordering = ["orden", "codigo"]

    def __str__(self):
        return f"{self.codigo} - {self.producto.nombre} - {self.presentacion.nombre}"