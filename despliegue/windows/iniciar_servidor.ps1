# Arranca la plataforma con Waitress. Lo ejecuta la tarea programada "TioCampo\Servidor"
# al encender el equipo; no hace falta abrirlo a mano. Si el proceso se cae, vuelve a
# arrancarlo a los 5 segundos.
#
# Solo escucha en 127.0.0.1: desde internet se entra únicamente por Tailscale Funnel (HTTPS).
# --url-scheme=https: Funnel ya entrega la conexión cifrada; así Django la reconoce como segura.

$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Logs = Join-Path $Raiz "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$Log = Join-Path $Logs "servidor.log"
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
$env:PYTHONUNBUFFERED = "1"
Set-Location $Raiz

while ($true) {
    # Rotación simple: si el log supera 10 MB se guarda como .1
    if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 10MB)) { Move-Item -Force $Log "$Log.1" }

    Add-Content -Path $Log -Value "$(Get-Date -Format s) Iniciando Waitress"
    # cmd /c para que la salida de error de Python vaya al log sin detener PowerShell.
    cmd /c "`"$Python`" -m waitress --listen=127.0.0.1:8000 --threads=8 --url-scheme=https --channel-timeout=120 config.wsgi:application >> `"$Log`" 2>&1"
    Add-Content -Path $Log -Value "$(Get-Date -Format s) Waitress terminó (código $LASTEXITCODE); se reinicia en 5 s"
    Start-Sleep -Seconds 5
}
