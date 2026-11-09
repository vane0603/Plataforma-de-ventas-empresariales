# Despliegue de Tío Campo en un servidor Windows

**Resultado:** la plataforma queda en internet con HTTPS (`https://tiocampo.xxxx.ts.net`), arranca
sola al encender el equipo, se respalda cada noche y se actualiza con un solo comando.

```
Clientes (internet) ──HTTPS──► Tailscale Funnel ──► Waitress 127.0.0.1:8000 ──► MySQL
                                (sin abrir puertos)    (Django + WhiteNoise)
```

| Pieza | Para qué |
|---|---|
| **Waitress** | Servidor de Python para Windows que ejecuta la plataforma |
| **WhiteNoise** | Entrega CSS, JS e íconos con caché y compresión |
| **MySQL** | Base de datos (servicio de Windows) |
| **Tailscale Funnel** | Publica la plataforma con HTTPS sin abrir puertos del router |
| **Programador de tareas** | Arranque automático, reintento de avisos, anonimización y respaldos |

Tiempo estimado: 1 a 2 horas la primera vez.

---

## Fase 0. Preparar el equipo servidor

1. **Nombre del equipo:** *Configuración → Sistema → Información → Cambiar el nombre de este equipo* →
   `tiocampo` → reiniciar. (La dirección pública será `tiocampo.xxxx.ts.net`.)
2. **Que nunca se suspenda** (PowerShell como administrador):
   ```
   powercfg /change standby-timeout-ac 0
   powercfg /change hibernate-timeout-ac 0
   powercfg /hibernate off
   ```
3. **Que se encienda solo tras un corte de luz:** en la BIOS/UEFI (tecla `Supr` o `F2` al encender) busca
   *Restore on AC Power Loss* (o *AC Back*) → **Power On**.
4. **Conexión por cable de red** (más estable que Wi-Fi) y, si es posible, una **UPS**.
5. **Windows Update:** déjalo activo. Cuando reinicie, la plataforma vuelve a arrancar sola.

## Fase 1. Instalar los programas (en el servidor)

1. **Python 3.14** — python.org → Downloads → *Windows installer (64-bit)*.
   En el instalador marca **Add python.exe to PATH** → **Customize installation** → Next →
   marca **Install Python for all users** → Install.
2. **Git** — git-scm.com → Download for Windows → instalar con las opciones por defecto.
3. **MySQL Server** — igual que en tu computador (MySQL Installer / MySQL Configurator):
   - *Development Computer* → puerto **3306**.
   - **Desmarca** *Open Windows Firewall ports for network access* (no hace falta: todo es local).
   - Contraseña de **root**: guárdala bien.
   - *Configure MySQL Server as a Windows Service* + *Start at System Startup*.

## Fase 2. Descargar el proyecto

PowerShell **como administrador**:
```
mkdir C:\TioCampo
cd C:\TioCampo
git clone https://github.com/vane0603/Plataforma-de-ventas-empresariales.git plataforma-ventas
cd plataforma-ventas
```

## Fase 3. Instalar la plataforma

En la misma ventana (dentro de `C:\TioCampo\plataforma-ventas`):
```
powershell -ExecutionPolicy Bypass -File despliegue\windows\instalar.ps1
```
(Si tienes un segundo disco para respaldos, agrega `-CopiaRespaldos "D:\RespaldosTioCampo"`.)

El script, en 6 pasos:
1. Verifica Python, Git y MySQL.
2. Crea el entorno virtual e instala las dependencias.
3. Crea la base `tio_campo` y el usuario `tiocampo` con una clave aleatoria (te pide **la contraseña de
   root** de MySQL) y genera el `.env` de producción con claves nuevas.
4. Crea las tablas y prepara los archivos estáticos.
5. Registra 4 tareas en el *Programador de tareas → Biblioteca → TioCampo*:
   **Servidor** (al encender), **Reintentar avisos** (cada 20 min), **Anonimizar datos** (2:30 a. m.) y
   **Respaldo** (1:30 a. m.).
6. Arranca la plataforma y comprueba que responde en `http://127.0.0.1:8000`.

> **MUY IMPORTANTE — guarda una copia del archivo `.env`** (en una memoria USB o en un gestor de
> contraseñas, nunca en GitHub). Contiene `DATOS_CIFRADO_CLAVES`: **sin ella no se pueden leer los
> documentos y teléfonos guardados**, ni siquiera desde un respaldo.

## Fase 4. Pasar tus datos actuales al servidor

**En tu computador actual** (el de desarrollo, con la plataforma detenida), PowerShell en `plataforma-ventas`
con una memoria USB conectada (ej. `E:`):
```
powershell -ExecutionPolicy Bypass -File despliegue\windows\exportar_datos.ps1 -Destino E:\migracion
```
**En el servidor** (PowerShell como administrador, en `C:\TioCampo\plataforma-ventas`):
```
powershell -ExecutionPolicy Bypass -File despliegue\windows\importar_datos.ps1 -Origen E:\migracion
```
Carga los datos, los cifra con las claves del servidor y copia imágenes y firmas.
**Después borra `E:\migracion\respaldo.json`**: contiene datos personales sin cifrar.

*(Si prefieres empezar sin datos: `.venv\Scripts\python manage.py createsuperuser`.)*

## Fase 5. Publicar en internet con Tailscale Funnel

1. Crea una cuenta gratuita en **tailscale.com** (puedes entrar con Google o Microsoft).
2. En el servidor descarga **Tailscale para Windows** desde tailscale.com/download, instálalo e inicia sesión.
3. Clic en el ícono de Tailscale (junto al reloj) → **Settings / Preferences** → activa **Run unattended**
   (así funciona aunque nadie haya iniciado sesión en Windows).
4. PowerShell como administrador:
   ```
   tailscale funnel --bg 8000
   ```
   La primera vez muestra un enlace para **habilitar HTTPS y Funnel** en tu cuenta: ábrelo, acepta y
   vuelve a ejecutar el comando. Al final muestra la dirección, por ejemplo
   `https://tiocampo.tail1234.ts.net`.
5. Registra esa dirección en la plataforma:
   ```
   powershell -ExecutionPolicy Bypass -File despliegue\windows\dominio.ps1 -Dominio tiocampo.tail1234.ts.net
   ```
6. **Prueba desde tu celular con datos móviles** (no con el Wi-Fi de la casa).

Ver el estado en cualquier momento: `tailscale funnel status`.

## Fase 6. Comprobaciones finales

- [ ] La dirección `https://…ts.net` abre la tienda en el celular con datos móviles.
- [ ] Puedes iniciar sesión en `https://…ts.net/admin/`.
- [ ] En el *Programador de tareas → TioCampo* están las 4 tareas.
- [ ] **Reinicia el servidor** y, sin iniciar sesión en Windows, la tienda vuelve a abrir en 1–2 minutos.
- [ ] Al día siguiente hay un archivo `tiocampo_AAAAMMDD_HHMM.zip` en `C:\TioCampo\respaldos`.

---

## Día a día

| Necesito… | Comando (PowerShell como administrador, en `C:\TioCampo\plataforma-ventas`) |
|---|---|
| Publicar cambios nuevos | En tu PC: `git push`. En el servidor: `powershell -ExecutionPolicy Bypass -File despliegue\windows\actualizar.ps1` (hace respaldo, descarga, migra y reinicia) |
| Reiniciar tras editar el `.env` (correo, WhatsApp…) | `powershell -ExecutionPolicy Bypass -File despliegue\windows\reiniciar.ps1` |
| Hacer un respaldo ahora | `powershell -ExecutionPolicy Bypass -File despliegue\windows\respaldo.ps1` |
| Ver errores | `C:\TioCampo\plataforma-ventas\logs\servidor.log` y `logs\tareas.log` |

### Restaurar un respaldo
1. Descomprime `tiocampo_AAAAMMDD_HHMM.zip`.
2. Detén la plataforma: `Stop-ScheduledTask -TaskPath "\TioCampo\" -TaskName "Servidor"`.
3. Base de datos: abre **MySQL Command Line Client** (contraseña de root) y escribe
   (con barras `/` en la ruta):
   ```
   USE tio_campo;
   SOURCE C:/ruta/del/respaldo/tio_campo.sql;
   ```
4. Copia las carpetas `media` y `privado` del respaldo dentro de `C:\TioCampo\plataforma-ventas`.
5. `reiniciar.ps1`.

(Debe usarse con el mismo `.env`: las claves de cifrado tienen que ser las del servidor.)

## Cuando compren el dominio
1. Compra el dominio y pásalo a **Cloudflare** (plan gratuito).
2. En el servidor instala **cloudflared** y crea un túnel (*Zero Trust → Networks → Tunnels*) que apunte a
   `http://localhost:8000` con el nombre `tiocampo.com.co` (o el que compren).
3. `dominio.ps1 -Dominio tiocampo.com.co` y apaga Funnel con `tailscale funnel reset`.

Tailscale Funnel es ideal para empezar; tiene límites de ancho de banda pensados para proyectos
pequeños. Con dominio propio y más tráfico, Cloudflare Tunnel es el paso natural.

## Seguridad: lo que ya queda configurado
- La plataforma solo escucha en `127.0.0.1`: nadie de la red local ni de internet llega directo a ella.
- MySQL no se expone a la red; el usuario `tiocampo` solo tiene permisos sobre su base.
- HTTPS obligatorio, cookies seguras, HSTS y protección CSRF (verificado).
- Las firmas de entrega (`privado/`) nunca se publican; las claves están solo en el `.env`.
- No abras puertos del router: no hace falta.
