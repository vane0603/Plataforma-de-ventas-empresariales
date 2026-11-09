# Funciones compartidas por instalar.ps1, actualizar.ps1 y dominio.ps1 (se cargan con ". .\comun.ps1").

$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
$CarpetaTareas = "\TioCampo\"

function Paso([string]$Texto) {
    Write-Host ""
    Write-Host "=== $Texto" -ForegroundColor Green
}

function Exigir-Administrador {
    $identidad = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $identidad.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Abra PowerShell como administrador (clic derecho > Ejecutar como administrador)."
    }
}

function Ejecutar([string]$Programa, [string[]]$Argumentos) {
    & $Programa @Argumentos
    if ($LASTEXITCODE -ne 0) { throw "Falló: $Programa $($Argumentos -join ' ')" }
}

function Manage([string[]]$Argumentos) {
    Ejecutar $Python (@("manage.py") + $Argumentos)
}

function Detener-Servidor {
    Stop-ScheduledTask -TaskPath $CarpetaTareas -TaskName "Servidor" -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like "*waitress*config.wsgi*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

function Iniciar-Servidor {
    Start-ScheduledTask -TaskPath $CarpetaTareas -TaskName "Servidor"
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0
            if ($r.StatusCode -eq 200) {
                Write-Host "La plataforma responde en el servidor (http://127.0.0.1:8000)." -ForegroundColor Green
                return
            }
        } catch { }
    }
    Write-Host "La plataforma no respondió. Revise $Raiz\logs\servidor.log" -ForegroundColor Red
}
