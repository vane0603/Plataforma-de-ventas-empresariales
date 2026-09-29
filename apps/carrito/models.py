from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.productos.models import ProductoPresentacion
from apps.promociones.models import Combo


class Carrito(models.Model):

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="carritos",
        blank=True,
        null=True,
    )

    session_key = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    activo = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Carrito"
        verbose_name_plural = "Carritos"

        constraints = [

            models.UniqueConstraint(
                fields=["usuario"],
                condition=Q(
                    usuario__isnull=False,
                    activo=True,
                ),
                name="unico_carrito_usuario_activo",
            ),

            models.UniqueConstraint(
                fields=["session_key"],
                condition=Q(
                    session_key__isnull=False,
                    activo=True,
                ),
                name="unico_carrito_session_activo",
            ),
        ]

    def __str__(self):

        if self.usuario:
            return f"Carrito de {self.usuario}"

        return f"Carrito sesión {self.session_key}"

    @property
    def total(self):

        return sum(
            item.subtotal
            for item in self.items.all()
        )

    @property
    def cantidad_items(self):

        return sum(
            item.cantidad
            for item in self.items.all()
        )


class CarritoItem(models.Model):

    carrito = models.ForeignKey(
        Carrito,
        on_delete=models.CASCADE,
        related_name="items",
    )

    # ==========================================
    # PRODUCTO NORMAL
    # ==========================================

    presentacion = models.ForeignKey(
        ProductoPresentacion,
        on_delete=models.PROTECT,
        related_name="items_carrito",
        blank=True,
        null=True,
    )

    # ==========================================
    # COMBO
    # ==========================================

    combo = models.ForeignKey(
        Combo,
        on_delete=models.PROTECT,
        related_name="items_carrito",
        blank=True,
        null=True,
    )

    cantidad = models.PositiveIntegerField(
        default=1,
    )

    precio_unitario = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:

        verbose_name = "Ítem del carrito"
        verbose_name_plural = "Ítems del carrito"

        constraints = [

            # El ítem debe tener:
            # producto O combo
            # nunca ambos
            models.CheckConstraint(
                condition=(
                    Q(
                        presentacion__isnull=False,
                        combo__isnull=True,
                    )
                    |
                    Q(
                        presentacion__isnull=True,
                        combo__isnull=False,
                    )
                ),
                name="carrito_item_un_solo_tipo",
            ),

            # Evita repetir el mismo producto
            # dentro del mismo carrito
            models.UniqueConstraint(
                fields=[
                    "carrito",
                    "presentacion",
                ],
                condition=Q(
                    presentacion__isnull=False,
                ),
                name="una_presentacion_por_carrito",
            ),

            # Evita repetir el mismo combo
            # dentro del mismo carrito
            models.UniqueConstraint(
                fields=[
                    "carrito",
                    "combo",
                ],
                condition=Q(
                    combo__isnull=False,
                ),
                name="un_combo_por_carrito",
            ),
        ]

    def __str__(self):

        return (
            f"{self.nombre_mostrar} "
            f"x {self.cantidad}"
        )

    # ==========================================
    # IDENTIFICAR TIPO
    # ==========================================

    @property
    def es_combo(self):

        return self.combo_id is not None

    @property
    def es_producto(self):

        return self.presentacion_id is not None

    # ==========================================
    # NOMBRE
    # ==========================================

    @property
    def nombre_mostrar(self):

        if self.combo_id:
            return self.combo.nombre

        if self.presentacion_id:
            return self.presentacion.producto.nombre

        return "Ítem"

    # ==========================================
    # DETALLE
    # ==========================================

    @property
    def detalle_mostrar(self):

        if self.combo_id:
            return "Combo promocional"

        if self.presentacion_id:

            if self.presentacion.presentacion:
                return self.presentacion.presentacion.nombre

        return ""

    # ==========================================
    # CÓDIGO
    # ==========================================

    @property
    def codigo_mostrar(self):

        if self.combo_id:

            return getattr(
                self.combo,
                "codigo",
                "",
            )

        if self.presentacion_id:

            return getattr(
                self.presentacion,
                "codigo",
                "",
            )

        return ""

    # ==========================================
    # CATEGORÍA
    # ==========================================

    @property
    def categoria_mostrar(self):

        if self.combo_id:
            return "COMBO"

        if self.presentacion_id:

            producto = self.presentacion.producto

            if producto.categoria:
                return producto.categoria.nombre

        return ""

    # ==========================================
    # IMAGEN
    # ==========================================

    @property
    def imagen_mostrar(self):

        if self.combo_id:

            return getattr(
                self.combo,
                "imagen",
                None,
            )

        if self.presentacion_id:

            return self.presentacion.producto.imagen

        return None

    # ==========================================
    # PRECIO ACTUAL
    # ==========================================

    @property
    def precio_vigente(self):

        if self.combo_id:

            return self.combo.precio

        if self.presentacion_id:

            return self.presentacion.precio

        return self.precio_unitario

    # ==========================================
    # SUBTOTAL
    # ==========================================

    @property
    def subtotal(self):

        return (
            self.precio_unitario
            *
            self.cantidad
        )