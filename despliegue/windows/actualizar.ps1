# Publica en el servidor la última versión subida a GitHub. Ejecutar como administrador:
#
#   powershell -ExecutionPolicy Bypass -File despliegue\windows\actualizar.ps1
#
# Hace un respaldo, descarga los cambios, instala dependencias, aplica migraciones y reinicia.

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "comun.ps1")
Exigir-Administrador
Set-Location $Raiz

Paso "1/5 Respaldo previo"
& (Join-Path $PSScriptRoot "respaldo.ps1")

Paso "2/5 Descargando cambios de GitHub"
Ejecutar "git" @("pull", "--ff-only")

Paso "3/5 Dependencias"
Ejecutar $Python @("-m", "pip", "install", "-r", "requirements.txt", "--quiet")

Paso "4/5 Migraciones y archivos estáticos"
Detener-Servidor
Manage @("migrate", "--noinput")
Manage @("collectstatic", "--noinput", "--verbosity", "0")

Paso "5/5 Reiniciando"
Iniciar-Servidor
