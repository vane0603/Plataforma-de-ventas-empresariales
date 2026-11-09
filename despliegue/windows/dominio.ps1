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
# Si antes estaba en modo red local, se cierra el puerto de la red de la oficina.
Remove-NetFirewallRule -DisplayName "Tio Campo (red local)" -ErrorAction SilentlyContinue
Detener-Servidor
Iniciar-Servidor
