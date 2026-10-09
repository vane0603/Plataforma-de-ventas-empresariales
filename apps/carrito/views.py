from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.productos.models import ProductoPresentacion
from apps.promociones.models import Combo

from .models import Carrito, CarritoItem


SESSION_CARRITO_ID = "carrito_id"


# ==========================================================
# FUSIONAR CARRITO DE INVITADO CON CARRITO DEL USUARIO
# ==========================================================

def _fusionar_carrito_invitado(request, carrito_usuario):

    carrito_id = request.session.get(
        SESSION_CARRITO_ID
    )

    if not carrito_id:
        return carrito_usuario

    try:

        carrito_invitado = (
            Carrito.objects
            .prefetch_related(
                "items__presentacion",
                "items__combo",
            )
            .get(
                id=carrito_id,
                usuario__isnull=True,
                activo=True,
            )
        )

    except Carrito.DoesNotExist:

        request.session.pop(
            SESSION_CARRITO_ID,
            None,
        )

        return carrito_usuario

    if carrito_invitado.id == carrito_usuario.id:

        request.session.pop(
            SESSION_CARRITO_ID,
            None,
        )

        return carrito_usuario

    with transaction.atomic():

        for item in carrito_invitado.items.select_related(
            "presentacion__producto",
            "presentacion__presentacion",
            "combo",
        ):

            # ==================================================
            # COMBO
            # ==================================================

            if item.combo_id:

                item_usuario, created = (
                    CarritoItem.objects.get_or_create(
                        carrito=carrito_usuario,
                        combo=item.combo,
                        defaults={
                            "presentacion": None,
                            "cantidad": item.cantidad,
                            "precio_unitario": item.combo.precio,
                        },
                    )
                )

            # ==================================================
            # PRODUCTO NORMAL
            # ==================================================

            else:

                item_usuario, created = (
                    CarritoItem.objects.get_or_create(
                        carrito=carrito_usuario,
                        presentacion=item.presentacion,
                        defaults={
                            "combo": None,
                            "cantidad": item.cantidad,
                            "precio_unitario": item.presentacion.precio,
                        },
                    )
                )

            # ==================================================
            # SI YA EXISTÍA
            # ==================================================

            if not created:

                nueva_cantidad = (
                    item_usuario.cantidad
                    +
                    item.cantidad
                )

                # Control de stock para combos
                if (
                    item_usuario.combo_id
                    and
                    item_usuario.combo.stock > 0
                ):

                    nueva_cantidad = min(
                        nueva_cantidad,
                        item_usuario.combo.stock,
                    )

                item_usuario.cantidad = nueva_cantidad

                item_usuario.precio_unitario = (
                    item_usuario.precio_vigente
                )

                item_usuario.save(
                    update_fields=[
                        "cantidad",
                        "precio_unitario",
                        "updated_at",
                    ]
                )

        carrito_invitado.activo = False

        carrito_invitado.save(
            update_fields=[
                "activo",
                "updated_at",
            ]
        )

    request.session.pop(
        SESSION_CARRITO_ID,
        None,
    )

    return carrito_usuario


# ==========================================================
# OBTENER CARRITO
# ==========================================================

def obtener_carrito(request):

    # ======================================================
    # USUARIO AUTENTICADO
    # ======================================================

    if request.user.is_authenticated:

        carrito, _ = Carrito.objects.get_or_create(
            usuario=request.user,
            activo=True,
            defaults={
                "session_key": None,
            },
        )

        return _fusionar_carrito_invitado(
            request,
            carrito,
        )

    # ======================================================
    # USUARIO INVITADO
    # ======================================================

    if not request.session.session_key:
        request.session.create()

    session_key = request.session.session_key

    carrito, _ = Carrito.objects.get_or_create(
        session_key=session_key,
        activo=True,
        defaults={
            "usuario": None,
        },
    )

    request.session[
        SESSION_CARRITO_ID
    ] = carrito.id

    return carrito


# ==========================================================
# DETALLE DEL CARRITO
# ==========================================================

def detalle_carrito(request):

    carrito = obtener_carrito(request)

    items = (
        carrito.items
        .select_related(
            "presentacion",
            "presentacion__producto",
            "presentacion__producto__categoria",
            "presentacion__presentacion",
            "combo",
        )
        .order_by(
            "-created_at"
        )
    )

    return render(
        request,
        "carrito/detalle.html",
        {
            "carrito": carrito,
            "items": items,
        },
    )


# ==========================================================
# AGREGAR PRODUCTO NORMAL
# ==========================================================

@require_POST
def agregar_al_carrito(
    request,
    presentacion_id,
):

    presentacion = get_object_or_404(
        ProductoPresentacion.objects.select_related(
            "producto",
            "presentacion",
        ),
        id=presentacion_id,
        activo=True,
        producto__activo=True,
    )

    try:

        cantidad = int(
            request.POST.get(
                "cantidad",
                "1",
            )
        )

    except (TypeError, ValueError):

        cantidad = 1

    cantidad = max(
        cantidad,
        1,
    )

    carrito = obtener_carrito(
        request
    )

    with transaction.atomic():

        item, created = (
            CarritoItem.objects.get_or_create(
                carrito=carrito,
                presentacion=presentacion,
                defaults={
                    "combo": None,
                    "cantidad": cantidad,
                    "precio_unitario": presentacion.precio,
                },
            )
        )

        if not created:

            item.cantidad += cantidad

            item.precio_unitario = (
                presentacion.precio
            )

            item.save(
                update_fields=[
                    "cantidad",
                    "precio_unitario",
                    "updated_at",
                ]
            )

    messages.success(
        request,
        f"{presentacion.producto.nombre} fue agregado al carrito.",
    )

    return redirect(
        "carrito:detalle"
    )


# ==========================================================
# AGREGAR COMBO
# ==========================================================

@require_POST
def agregar_combo(
    request,
    combo_id,
):

    combo = get_object_or_404(
        Combo,
        id=combo_id,
        activo=True,
    )

    # ======================================================
    # VALIDAR STOCK
    # ======================================================

    if combo.stock < 1:

        messages.warning(
            request,
            f"El combo {combo.nombre} está agotado.",
        )

        return redirect(
            "combos:detalle_combo",
            pk=combo.id,
        )

    # ======================================================
    # CANTIDAD
    # ======================================================

    try:

        cantidad = int(
            request.POST.get(
                "cantidad",
                "1",
            )
        )

    except (TypeError, ValueError):

        cantidad = 1

    cantidad = max(
        cantidad,
        1,
    )

    # ======================================================
    # OBTENER CARRITO
    # ======================================================

    carrito = obtener_carrito(
        request
    )

    # ======================================================
    # CREAR / ACTUALIZAR COMBO
    # ======================================================

    with transaction.atomic():

        item, created = (
            CarritoItem.objects.get_or_create(
                carrito=carrito,
                combo=combo,
                defaults={
                    "presentacion": None,
                    "cantidad": min(
                        cantidad,
                        combo.stock,
                    ),
                    "precio_unitario": combo.precio,
                },
            )
        )

        # ==================================================
        # EL COMBO YA ESTABA EN EL CARRITO
        # ==================================================

        if not created:

            nueva_cantidad = (
                item.cantidad
                +
                cantidad
            )

            if nueva_cantidad > combo.stock:

                item.cantidad = combo.stock

                messages.warning(
                    request,
                    f"Solo hay {combo.stock} unidad(es) disponibles.",
                )

            else:

                item.cantidad = nueva_cantidad

            # Actualizar precio
            item.precio_unitario = combo.precio

            item.save(
                update_fields=[
                    "cantidad",
                    "precio_unitario",
                    "updated_at",
                ]
            )

    # ======================================================
    # MENSAJE
    # ======================================================

    messages.success(
        request,
        f"{combo.nombre} fue agregado al carrito.",
    )

    # ======================================================
    # IR AL CARRITO
    # ======================================================

    return redirect(
        "carrito:detalle"
    )


# ==========================================================
# ACTUALIZAR ITEM
# ==========================================================

@require_POST
def actualizar_item(
    request,
    item_id,
):

    carrito = obtener_carrito(
        request
    )

    item = get_object_or_404(
        CarritoItem.objects.select_related(
            "presentacion",
            "combo",
        ),
        id=item_id,
        carrito=carrito,
    )

    try:

        cantidad = int(
            request.POST.get(
                "cantidad",
                "1",
            )
        )

    except (TypeError, ValueError):

        cantidad = 1

    # ======================================================
    # ELIMINAR SI ES MENOR A 1
    # ======================================================

    if cantidad < 1:

        item.delete()

        messages.info(
            request,
            "Ítem eliminado del carrito.",
        )

        return redirect(
            "carrito:detalle"
        )

    # ======================================================
    # VALIDAR COMBO
    # ======================================================

    if item.combo_id:

        if not item.combo.activo:

            item.delete()

            messages.warning(
                request,
                "El combo ya no está disponible.",
            )

            return redirect(
                "carrito:detalle"
            )

        if item.combo.stock < 1:

            item.delete()

            messages.warning(
                request,
                "El combo está agotado.",
            )

            return redirect(
                "carrito:detalle"
            )

        if cantidad > item.combo.stock:

            cantidad = item.combo.stock

            messages.warning(
                request,
                f"La cantidad fue ajustada a {item.combo.stock}.",
            )

    # ======================================================
    # ACTUALIZAR
    # ======================================================

    item.cantidad = cantidad

    item.precio_unitario = (
        item.precio_vigente
    )

    item.save(
        update_fields=[
            "cantidad",
            "precio_unitario",
            "updated_at",
        ]
    )

    messages.success(
        request,
        "Cantidad actualizada.",
    )

    return redirect(
        "carrito:detalle"
    )


# ==========================================================
# ELIMINAR ITEM
# ==========================================================

@require_POST
def eliminar_item(
    request,
    item_id,
):

    carrito = obtener_carrito(
        request
    )

    item = get_object_or_404(
        CarritoItem,
        id=item_id,
        carrito=carrito,
    )

    item.delete()

    messages.success(
        request,
        "Ítem eliminado del carrito.",
    )

    return redirect(
        "carrito:detalle"
    )


# ==========================================================
# VACIAR CARRITO
# ==========================================================

@require_POST
def vaciar_carrito(request):

    carrito = obtener_carrito(
        request
    )

    carrito.items.all().delete()

    messages.success(
        request,
        "El carrito fue vaciado.",
    )

    return redirect(
        "carrito:detalle"
    )