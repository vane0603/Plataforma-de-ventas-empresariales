# Arranca la plataforma con Waitress. Lo ejecuta la tarea programada "TioCampo\Servidor"
# al encender el equipo; no hace falta abrirlo a mano. Si el proceso se cae, vuelve a
# arrancarlo a los 5 segundos.
#
# Por defecto solo escucha en 127.0.0.1: desde internet se entra únicamente por Tailscale Funnel
# (HTTPS), y --url-scheme=https le dice a Django que la conexión ya llega cifrada.
# En "modo red local" (red_local.ps1) el .env trae SERVIDOR_ESCUCHA=0.0.0.0:8000 y
# SERVIDOR_ESQUEMA=http para atender a los equipos del Wi-Fi de la oficina.

$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Logs = Join-Path $Raiz "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$Log = Join-Path $Logs "servidor.log"
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
$env:PYTHONUNBUFFERED = "1"
Set-Location $Raiz

function Valor-Env([string]$Clave, [string]$Defecto) {
    $linea = Get-Content (Join-Path $Raiz ".env") -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^\s*$Clave\s*=" } | Select-Object -Last 1
    if ($linea) { $valor = ($linea -split "=", 2)[1].Trim(); if ($valor) { return $valor } }
    return $Defecto
}
$Escucha = Valor-Env "SERVIDOR_ESCUCHA" "127.0.0.1:8000"
$Esquema = Valor-Env "SERVIDOR_ESQUEMA" "https"

while ($true) {
    # Rotación simple: si el log supera 10 MB se guarda como .1
    if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 10MB)) { Move-Item -Force $Log "$Log.1" }

    Add-Content -Path $Log -Value "$(Get-Date -Format s) Iniciando Waitress en $Escucha ($Esquema)"
    # cmd /c para que la salida de error de Python vaya al log sin detener PowerShell.
    cmd /c "`"$Python`" -m waitress --listen=$Escucha --threads=8 --url-scheme=$Esquema --channel-timeout=120 config.wsgi:application >> `"$Log`" 2>&1"
    Add-Content -Path $Log -Value "$(Get-Date -Format s) Waitress terminó (código $LASTEXITCODE); se reinicia en 5 s"
    Start-Sleep -Seconds 5
}
