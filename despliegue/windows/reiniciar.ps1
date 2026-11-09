# Reinicia la plataforma (por ejemplo, después de editar el .env). Ejecutar como administrador:
#
#   powershell -ExecutionPolicy Bypass -File despliegue\windows\reiniciar.ps1

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "comun.ps1")
Exigir-Administrador
Detener-Servidor
Iniciar-Servidor
