# Tío Campo · Plataforma de ventas con descuento por nómina

Tienda en línea de productos del campo para empleados de empresas con convenio. Además de pagar
en línea u otro medio, el comprador puede pagar con **descuento por nómina**: su **fondo de
empleados** verifica que trabaje en la empresa, revisa su cupo y aprueba **total, parcial o
rechaza** la compra. El pedido se entrega en la **finca** donde trabaja y el empleado **firma
al recibir**.

## Funcionalidades

**Tienda**
- Catálogo con buscador, categorías, combos y ofertas, diseño adaptado a celular.
- Carrito sin recargar la página; compra como invitado (pago en línea u otro medio).
- Pago en línea con **Wompi** (tarjeta, PSE, Nequi, Bancolombia).

**Descuento por nómina**
- Verificación del empleado por **revisión manual**, **padrón de afiliados (CSV)** o **API del fondo**.
- Decisión **automática o del gestor**: aprobación total, parcial (el saldo se paga con otro medio) o rechazo.
- Cupo por afiliado con bloqueo seguro ante compras simultáneas.
- **Reporte mensual por fondo** (Excel/CSV) y cierre de corte para que el fondo aplique el descuento.

**Entregas**
- Fincas por fondo como punto de entrega.
- Panel de repartidores con pestañas **Por entregar / Entregados**, firma en pantalla para nómina y constancia imprimible.

**Datos personales (Ley 1581 de 2012)**
- Documento y teléfono **cifrados** en la base de datos; firmas en carpeta privada.
- Autorización de tratamiento de datos registrada (registro, compra de invitado y nómina).
- Política de datos publicada y anonimización automática al vencer el plazo de retención.

**API REST** v1 con documentación interactiva en `/api/docs/`.

## Tecnología
Python 3.12+ · Django 6 · Django REST Framework · MySQL 8+ (o PostgreSQL) / SQLite (pruebas rápidas) ·
Bootstrap 5 · Wompi · cryptography · openpyxl.

## Instalación (desarrollo, Windows)

```powershell
git clone https://github.com/vane0603/Plataforma-de-ventas-empresariales.git
cd Plataforma-de-ventas-empresariales
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python manage.py generar_clave_cifrado     # pegue las dos líneas en el .env
# Base de datos: complete el bloque DB_ del .env (ver "Base de datos MySQL")
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Abra http://127.0.0.1:8000 y el administrador en http://127.0.0.1:8000/admin.

**Probar desde el celular** (misma red Wi-Fi): agregue la IP del computador a `ALLOWED_HOSTS`,
marque la red de Windows como *Privada* y arranque con `python manage.py runserver 0.0.0.0:8000`.

## Base de datos MySQL
Cree la base y el usuario (MySQL Command Line Client, como root):

```sql
CREATE DATABASE tio_campo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'tiocampo'@'localhost' IDENTIFIED BY 'una-clave-segura';
GRANT ALL PRIVILEGES ON tio_campo.* TO 'tiocampo'@'localhost';
GRANT ALL PRIVILEGES ON test_tio_campo.* TO 'tiocampo'@'localhost';
```

Y en el `.env`: `DB_ENGINE=django.db.backends.mysql`, `DB_NAME=tio_campo`, `DB_USER=tiocampo`,
`DB_PASSWORD=...`, `DB_PORT=3306`. Si deja `DB_NAME` vacío se usa SQLite (`db.sqlite3`).

## Configuración inicial (en `/admin`)
1. **Catálogo:** categorías (con ícono), marcas, presentaciones, productos y combos.
2. **Fondos de empleados:** modo de verificación, gestores y **fincas** (puntos de entrega).
3. **Padrón:** cárguelo desde *Gestionar nómina → Padrón* o con `importar_padron`.
4. **Repartidores:** agregue usuarios al grupo **"Repartidores"**.
5. **Banners** de la portada (opcional).

## Comandos útiles

| Comando | Para qué |
|---|---|
| `python manage.py test` | Ejecuta las pruebas automáticas |
| `python manage.py importar_padron "FONDO" archivo.csv` | Carga el padrón de afiliados |
| `python manage.py corte_nomina --cerrar --enviar` | Cierra el corte mensual y lo envía a cada fondo |
| `python manage.py anonimizar_datos` | Borra datos personales vencidos (programar diario) |
| `python manage.py generar_clave_cifrado` | Genera claves de cifrado |
| `python manage.py recifrar_datos` | Vuelve a cifrar tras cambiar/rotar claves |

## Estructura

```
apps/
  api/          API REST v1 (Django REST Framework)
  carrito/      Carrito de compras
  catalogos/    Categorías, marcas, presentaciones
  core/         Cifrado de datos personales
  cuentas/      Registro y autorizaciones de datos
  dashboard/    Portada, banners y menú
  fondos/       Fondos, padrón, verificación, nómina, fincas, reportes
  pagos/        Pasarela de pagos (Wompi)
  pedidos/      Checkout, pedidos y entregas con firma
  productos/    Productos y catálogo
  promociones/  Combos
config/         Configuración de Django
templates/      Plantillas HTML
static/         CSS y JavaScript de la tienda
```

## Seguridad
- No suba el `.env`, bases `*.sqlite3`, respaldos `respaldo*.json`, `media/` ni `privado/` (ya están en `.gitignore`).
- Guarde `DATOS_CIFRADO_CLAVES` en un lugar seguro: sin ella los datos cifrados no se recuperan.
- La política de datos (`/politica-de-datos/`) es una plantilla: debe revisarla el área jurídica.

## Despliegue
Servidor Linux con Nginx + Gunicorn + MySQL (o PostgreSQL) + HTTPS (Let's Encrypt). Con `DEBUG=0` la
aplicación exige `DJANGO_SECRET_KEY` y las claves de cifrado. Incluya `privado/` y la base de
datos en las copias de seguridad.
