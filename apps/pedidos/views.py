from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from apps.carrito.views import obtener_carrito

from .models import Pedido, PedidoItem


@login_required
def checkout(request):

    carrito = obtener_carrito(
        request
    )

    items = (
        carrito.items
        .select_related(
            "presentacion",
            "presentacion__producto",
            "presentacion__presentacion",
            "combo",
        )
        .order_by("id")
    )

    if not items.exists():

        messages.warning(
            request,
            "Tu carrito está vacío.",
        )

        return redirect(
            "carrito:detalle"
        )


    total = carrito.total


    if request.method == "POST":

        metodo_pago = (
            request.POST
            .get(
                "metodo_pago",
                "",
            )
            .strip()
        )

        direccion = (
            request.POST
            .get(
                "direccion_entrega",
                "",
            )
            .strip()
        )

        ciudad = (
            request.POST
            .get(
                "ciudad",
                "",
            )
            .strip()
        )

        observaciones = (
            request.POST
            .get(
                "observaciones",
                "",
            )
            .strip()
        )


        metodos_validos = {
            codigo
            for codigo, _
            in Pedido.METODOS_PAGO
        }


        if metodo_pago not in metodos_validos:

            messages.error(
                request,
                "Debes seleccionar un medio de pago válido.",
            )

            return redirect(
                "pedidos:checkout"
            )


        if not direccion:

            messages.error(
                request,
                "Debes ingresar la dirección de entrega.",
            )

            return redirect(
                "pedidos:checkout"
            )


        if not ciudad:

            messages.error(
                request,
                "Debes ingresar la ciudad de entrega.",
            )

            return redirect(
                "pedidos:checkout"
            )


        with transaction.atomic():

            carrito = (
                type(carrito)
                .objects
                .select_for_update()
                .get(
                    pk=carrito.pk
                )
            )


            items_bloqueados = list(

                carrito.items
                .select_for_update()
                .select_related(
                    "presentacion__producto",
                    "presentacion__presentacion",
                    "combo",
                )

            )


            if (
                not carrito.activo
                or
                not items_bloqueados
            ):

                messages.warning(
                    request,
                    "Este carrito ya fue procesado.",
                )

                return redirect(
                    "carrito:detalle"
                )


            # ===============================
            # VALIDAR PRODUCTOS Y COMBOS
            # ===============================

            for item in items_bloqueados:

                if item.combo_id:

                    combo = item.combo

                    if not combo.activo:

                        messages.error(
                            request,
                            f"El combo {combo.nombre} ya no está disponible.",
                        )

                        return redirect(
                            "carrito:detalle"
                        )


                    if combo.stock < item.cantidad:

                        messages.error(
                            request,
                            (
                                f"El combo {combo.nombre} "
                                f"solo tiene {combo.stock} "
                                "unidad(es) disponibles."
                            ),
                        )

                        return redirect(
                            "carrito:detalle"
                        )


                    item.precio_unitario = (
                        combo.precio
                    )


                else:

                    presentacion = (
                        item.presentacion
                    )


                    if (
                        not presentacion
                        or
                        not presentacion.activo
                        or
                        not presentacion.producto.activo
                    ):

                        messages.error(
                            request,
                            (
                                "Uno de los productos "
                                "del carrito ya no está disponible."
                            ),
                        )

                        return redirect(
                            "carrito:detalle"
                        )


                    item.precio_unitario = (
                        presentacion.precio
                    )


                item.save(
                    update_fields=[
                        "precio_unitario",
                        "updated_at",
                    ]
                )


            total = sum(
                item.subtotal
                for item
                in items_bloqueados
            )


            if (
                metodo_pago
                ==
                Pedido.METODO_NOMINA
            ):

                estado = (
                    Pedido
                    .ESTADO_PENDIENTE_SOLICITUD_NOMINA
                )

            else:

                estado = (
                    Pedido
                    .ESTADO_PENDIENTE_PAGO
                )


            pedido = Pedido.objects.create(

                usuario=request.user,

                carrito=carrito,

                metodo_pago=metodo_pago,

                estado=estado,

                subtotal=total,

                total=total,

                direccion_entrega=direccion,

                ciudad=ciudad,

                observaciones=observaciones,
            )


            # ===============================
            # COPIAR ITEMS AL PEDIDO
            # ===============================

            for item in items_bloqueados:

                if item.combo_id:

                    PedidoItem.objects.create(

                        pedido=pedido,

                        combo=item.combo,

                        producto_presentacion=None,

                        producto_nombre=(
                            item.combo.nombre
                        ),

                        referencia=(
                            item.combo.codigo
                        ),

                        presentacion=(
                            "Combo promocional"
                        ),

                        cantidad=item.cantidad,

                        precio_unitario=(
                            item.precio_unitario
                        ),

                        subtotal=(
                            item.subtotal
                        ),
                    )


                else:

                    PedidoItem.objects.create(

                        pedido=pedido,

                        combo=None,

                        producto_presentacion=(
                            item.presentacion
                        ),

                        producto_nombre=(
                            item
                            .presentacion
                            .producto
                            .nombre
                        ),

                        referencia=(
                            item
                            .presentacion
                            .codigo
                        ),

                        presentacion=(
                            item
                            .presentacion
                            .presentacion
                            .nombre
                        ),

                        cantidad=item.cantidad,

                        precio_unitario=(
                            item.precio_unitario
                        ),

                        subtotal=(
                            item.subtotal
                        ),
                    )


            carrito.activo = False

            carrito.save(
                update_fields=[
                    "activo",
                    "updated_at",
                ]
            )


        # ===================================
        # DESCUENTO POR NÓMINA
        # ===================================

        if (
            metodo_pago
            ==
            Pedido.METODO_NOMINA
        ):

            return redirect(
                "fondos:solicitar_descuento_nomina",
                pedido_id=pedido.id,
            )


        messages.success(
            request,
            (
                f"Pedido {pedido.numero} "
                "creado correctamente."
            ),
        )

        return redirect(
            "pedidos:confirmacion",
            pedido_id=pedido.id,
        )


    return render(
        request,
        "pedidos/checkout.html",
        {
            "carrito": carrito,
            "items": items,
            "total": total,
        },
    )


@login_required
def confirmacion(
    request,
    pedido_id,
):

    pedido = get_object_or_404(

        Pedido.objects
        .prefetch_related(
            "items"
        ),

        id=pedido_id,

        usuario=request.user,
    )

    return render(
        request,
        "pedidos/confirmacion.html",
        {
            "pedido": pedido,
        },
    )


@login_required
def mis_pedidos(request):

    pedidos = (

        Pedido.objects
        .filter(
            usuario=request.user
        )
        .prefetch_related(
            "items"
        )
        .order_by(
            "-created_at"
        )

    )

    return render(
        request,
        "pedidos/mis_pedidos.html",
        {
            "pedidos": pedidos,
        },
    )