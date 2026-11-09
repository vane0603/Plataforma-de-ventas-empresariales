# Ejecuta un comando de manage.py y guarda la salida en logs\tareas.log.
# Lo usan las tareas programadas, p. ej.:  tarea.ps1 reenviar_notificaciones
param([Parameter(Mandatory = $true)][string]$Comando)

$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Logs = Join-Path $Raiz "logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$Log = Join-Path $Logs "tareas.log"
if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 5MB)) { Move-Item -Force $Log "$Log.1" }

Set-Location $Raiz
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
Add-Content -Path $Log -Value "$(Get-Date -Format s) $Comando"
cmd /c "`"$Python`" manage.py $Comando >> `"$Log`" 2>&1"
exit $LASTEXITCODE
