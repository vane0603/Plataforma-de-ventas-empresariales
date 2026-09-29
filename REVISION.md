# Revisión del flujo de ecommerce y descuento por nómina

## Problemas encontrados en el proyecto recibido

- El carrito tenía modelos y vistas, pero no existía su migración; la base incluida no tenía tablas de carrito.
- El botón **Continuar compra** estaba deshabilitado.
- El enlace **Carrito** del menú apuntaba a `#`.
- `pedidos/views.py` importaba `Pedido` y `PedidoItem`, pero `pedidos/models.py` estaba vacío.
- Las vistas de pedidos hacían referencia a `combo` y `nombre_mostrar`, campos que no existen en el carrito actual.
- `pedidos` no tenía URLs conectadas al proyecto ni plantilla de confirmación.
- La solicitud de nómina tomaba el total del carrito, pero no quedaba vinculada a un pedido ni conservaba una copia de los productos solicitados.
- La notificación al fondo estaba solamente comentada; no se enviaba nada.
- El fondo no tenía un portal restringido para validar vinculación, cupo y decisión.
- Las plantillas `mis_solicitudes.html`, `detalle_solicitud.html` y `seguridad/login.html` estaban vacías.
- Las migraciones históricas de `fondos` no coincidían con el modelo Python actual.

## Flujo implementado

1. El usuario agrega una presentación de producto al carrito.
2. En el carrito pulsa **Continuar compra**.
3. Si no inició sesión, Django solicita ingreso y luego recupera/fusiona el carrito de sesión.
4. En checkout ingresa dirección, ciudad y selecciona el medio de pago.
5. Se crea un `Pedido` y `PedidoItem` con una copia de productos, cantidades y precios.
6. Si selecciona **Descuento por nómina**, pasa al formulario de solicitud asociado al pedido.
7. La plataforma envía una notificación por correo al fondo y a sus usuarios gestores.
8. Un gestor autorizado entra a **Gestionar nómina**, valida si la persona pertenece a la entidad, reporta cupo y aprueba, aprueba parcialmente o rechaza.
9. La decisión actualiza automáticamente el estado del pedido y notifica al usuario por correo.
10. El usuario puede consultar **Mis pedidos** y **Mis solicitudes de nómina**.

## Configuración necesaria

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

En el administrador de Django:

1. Crear/editar el fondo de empleados.
2. Registrar un correo del fondo.
3. Asignar uno o más usuarios en el campo **gestores**.

En desarrollo, los correos se imprimen en consola. Para producción configure variables de entorno como `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` y `DEFAULT_FROM_EMAIL`.

## Pendiente para producción

- Integrar la pasarela de pago electrónico real.
- Definir cifrado/retención para documento, teléfono y otros datos personales.
- Agregar auditoría de cambios de las respuestas del fondo.
- Definir qué debe ocurrir comercialmente cuando la aprobación sea parcial (por ejemplo, permitir ajustar el pedido al cupo aprobado).
- Reemplazar SQLite por PostgreSQL y mover `SECRET_KEY`, credenciales y configuración sensible a variables de entorno.
