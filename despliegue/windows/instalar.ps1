# Instala Tío Campo en un servidor Windows (una sola vez). Ejecutar como administrador,
# dentro de la carpeta del proyecto:
#
#   powershell -ExecutionPolicy Bypass -File despliegue\windows\instalar.ps1
#
# Requisitos previos (ver LEEME): Python 3.12+, Git y MySQL Server instalados.
# Se puede volver a ejecutar sin problema: no borra datos ni cambia las claves del .env.
#
#   -Dominio          dirección pública (p. ej. tiocampo.xxxx.ts.net); se puede poner después con dominio.ps1
#   -CopiaRespaldos   carpeta extra para los respaldos (otro disco u OneDrive), p. ej. "D:\RespaldosTioCampo"
param([string]$Dominio = "", [string]$CopiaRespaldos = "")

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "comun.ps1")
Exigir-Administrador
Set-Location $Raiz

# ---------------------------------------------------------------- 1. Programas
Paso "1/6 Verificando programas"
# "py -3" (lanzador de python.org) o "python"; se ignora el acceso directo de Microsoft Store.
$PythonBase = $null
$PythonArgs = @()
foreach ($candidato in @("py|-3", "python|")) {
    $exe, $extra = $candidato.Split("|")
    $extra = @($extra | Where-Object { $_ })
    try {
        $version = (& $exe @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $version -and [version]$version -ge [version]"3.12") {
            $PythonBase = $exe; $PythonArgs = $extra; break
        }
    } catch { }
}
if (-not $PythonBase) { throw "Instale Python 3.12 o superior desde python.org (marque 'Add python.exe to PATH')." }
Write-Host "Python $version"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Instale Git desde git-scm.com." }

$Mysql = Get-ChildItem "C:\Program Files\MySQL\MySQL Server*\bin\mysql.exe" -ErrorAction SilentlyContinue | Select-Object -Last 1
if (-not $Mysql) { throw "Instale MySQL Server y configúrelo con MySQL Configurator." }
$Servicio = Get-Service -Name "MySQL*" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $Servicio -or $Servicio.Status -ne "Running") { throw "El servicio de MySQL no está en ejecución." }
Write-Host "MySQL: $($Mysql.Directory.Parent.Name) (servicio $($Servicio.Name))"

# ---------------------------------------------------------------- 2. Entorno de Python
Paso "2/6 Instalando dependencias de Python"
if (-not (Test-Path $Python)) {
    Ejecutar $PythonBase ($PythonArgs + @("-m", "venv", ".venv"))
}
Ejecutar $Python @("-m", "pip", "install", "--upgrade", "pip", "--quiet")
Ejecutar $Python @("-m", "pip", "install", "-r", "requirements.txt", "--quiet")

# ---------------------------------------------------------------- 3. Base de datos y .env
Paso "3/6 Base de datos y configuración"
if (Test-Path (Join-Path $Raiz ".env")) {
    Write-Host "Ya existe .env: se conserva (no se cambian claves ni contraseñas)."
} else {
    $Clave = & $Python -c "import secrets; print(secrets.token_urlsafe(24))"
    $Sql = @(
        "CREATE DATABASE IF NOT EXISTS tio_campo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        "CREATE USER IF NOT EXISTS 'tiocampo'@'localhost' IDENTIFIED BY '$Clave';",
        "ALTER USER 'tiocampo'@'localhost' IDENTIFIED BY '$Clave';",
        "GRANT ALL PRIVILEGES ON tio_campo.* TO 'tiocampo'@'localhost';",
        "GRANT ALL PRIVILEGES ON test_tio_campo.* TO 'tiocampo'@'localhost';",
        # Necesario para respaldos consistentes con mysqldump --single-transaction (MySQL 8+).
        "GRANT FLUSH_TABLES ON *.* TO 'tiocampo'@'localhost';"
    ) -join " "
    Write-Host "Escriba la contraseña de ROOT de MySQL (la que puso en MySQL Configurator):" -ForegroundColor Yellow
    & $Mysql.FullName -u root -p -e $Sql
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear la base de datos. ¿La contraseña de root es correcta?" }
    Ejecutar $Python @("despliegue\windows\configurar_env.py", "--crear", "--db-password", $Clave)
    Write-Host "La clave del usuario 'tiocampo' quedó guardada solo en el .env." -ForegroundColor Yellow
}
if ($Dominio) { Ejecutar $Python @("despliegue\windows\configurar_env.py", "--dominio", $Dominio) }

# ---------------------------------------------------------------- 4. Tablas y archivos
Paso "4/6 Creando tablas y preparando archivos"
Manage @("migrate", "--noinput")
Manage @("collectstatic", "--noinput", "--verbosity", "0")
New-Item -ItemType Directory -Force -Path (Join-Path $Raiz "media"), (Join-Path $Raiz "privado"), (Join-Path $Raiz "logs") | Out-Null

# ---------------------------------------------------------------- 5. Tareas programadas
Paso "5/6 Registrando tareas programadas (carpeta TioCampo)"
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

function Registrar([string]$Nombre, [string]$Argumentos, $Disparador, [TimeSpan]$Limite) {
    $accion = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $Raiz `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File $Argumentos"
    $ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit $Limite
    Register-ScheduledTask -TaskPath $CarpetaTareas -TaskName $Nombre -Action $accion -Trigger $Disparador `
        -Settings $ajustes -Principal $Principal -Force | Out-Null
    Write-Host "  - $Nombre"
}

$Scripts = Join-Path $Raiz "despliegue\windows"
Detener-Servidor
Registrar "Servidor" "`"$Scripts\iniciar_servidor.ps1`"" (New-ScheduledTaskTrigger -AtStartup) ([TimeSpan]::Zero)
Registrar "Reintentar avisos" "`"$Scripts\tarea.ps1`" reenviar_notificaciones" `
    (New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 20)) (New-TimeSpan -Minutes 15)
Registrar "Anonimizar datos" "`"$Scripts\tarea.ps1`" anonimizar_datos" `
    (New-ScheduledTaskTrigger -Daily -At "02:30") (New-TimeSpan -Hours 1)
$ArgsRespaldo = "`"$Scripts\respaldo.ps1`""
if ($CopiaRespaldos) { $ArgsRespaldo += " -CopiaEn `"$CopiaRespaldos`"" }
Registrar "Respaldo" $ArgsRespaldo (New-ScheduledTaskTrigger -Daily -At "01:30") (New-TimeSpan -Hours 2)

# ---------------------------------------------------------------- 6. Arranque
Paso "6/6 Iniciando la plataforma"
Iniciar-Servidor

Write-Host ""
Write-Host "Listo. Siguiente paso: publicar con Tailscale Funnel (LEEME, paso 5)." -ForegroundColor Green
