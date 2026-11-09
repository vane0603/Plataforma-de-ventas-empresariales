# Modo RED LOCAL: la plataforma solo se usa desde los equipos y celulares conectados a la red
# (Wi-Fi o cable) de la oficina, sin internet. Se entra por http://IP-DEL-SERVIDOR:8000
#
# Ejecutar como administrador, con la IP fija del servidor:
#   powershell -ExecutionPolicy Bypass -File despliegue\windows\red_local.ps1 -Ip 192.168.1.50
#
# Qué hace: ajusta el .env (http, IP permitida), abre el puerto 8000 en el firewall SOLO para
# la red local (perfil Privado/Dominio) y reinicia la plataforma.
# Para pasar después a internet con Tailscale: dominio.ps1 (deshace este modo).
param(
    [Parameter(Mandatory = $true)][string]$Ip,
    [int]$Puerto = 8000
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "comun.ps1")
Exigir-Administrador
Set-Location $Raiz

Paso "1/3 Configurando el .env para la red de la oficina ($Ip)"
Ejecutar $Python @("despliegue\windows\configurar_env.py", "--red-local", $Ip)

Paso "2/3 Abriendo el puerto $Puerto solo para la red local"
Remove-NetFirewallRule -DisplayName "Tio Campo (red local)" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "Tio Campo (red local)" -Direction Inbound -Protocol TCP -LocalPort $Puerto `
    -Action Allow -Profile Private, Domain -RemoteAddress LocalSubnet | Out-Null
$perfiles = Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -ne "Disconnected" }
foreach ($perfil in $perfiles) {
    if ($perfil.NetworkCategory -eq "Public") {
        Write-Host "La red '$($perfil.Name)' está como PÚBLICA: cámbiela a PRIVADA o los demás equipos no podrán entrar." -ForegroundColor Yellow
        Write-Host "  Configuración > Red e Internet > (su red) > Tipo de perfil de red > Privada" -ForegroundColor Yellow
    }
}

Paso "3/3 Reiniciando la plataforma"
Detener-Servidor
Iniciar-Servidor
Write-Host ""
Write-Host "Desde cualquier equipo o celular de la oficina entre a:  http://$($Ip):$Puerto" -ForegroundColor Green
