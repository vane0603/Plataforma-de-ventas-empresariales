# Configura la dirección pública (la de Tailscale Funnel o, más adelante, el dominio propio)
# y reinicia la plataforma. Ejecutar como administrador:
#
#   powershell -ExecutionPolicy Bypass -File despliegue\windows\dominio.ps1 -Dominio tiocampo.xxxx.ts.net
param([Parameter(Mandatory = $true)][string]$Dominio)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "comun.ps1")
Exigir-Administrador
Set-Location $Raiz

Ejecutar $Python @("despliegue\windows\configurar_env.py", "--dominio", $Dominio)
Detener-Servidor
Iniciar-Servidor
