# SE EJECUTA EN EL SERVIDOR, una sola vez, después de instalar.ps1. Ejecutar como administrador:
#
#   powershell -ExecutionPolicy Bypass -File despliegue\windows\importar_datos.ps1 -Origen E:\migracion
#
# Carga los datos exportados con exportar_datos.ps1, los cifra con las claves del servidor,
# recalcula las huellas de búsqueda y copia imágenes y firmas.
param([Parameter(Mandatory = $true)][string]$Origen)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "comun.ps1")
Exigir-Administrador
Set-Location $Raiz

$Json = Join-Path $Origen "respaldo.json"
if (-not (Test-Path $Json)) { throw "No se encontró $Json" }

Paso "1/4 Deteniendo la plataforma"
Detener-Servidor

Paso "2/4 Cargando datos"
$env:PYTHONUTF8 = "1"
Manage @("loaddata", $Json)

Paso "3/4 Cifrando con las claves del servidor"
Manage @("recifrar_datos")

Paso "4/4 Copiando imágenes y firmas"
foreach ($Carpeta in "media", "privado") {
    $Desde = Join-Path $Origen $Carpeta
    if (Test-Path $Desde) { Copy-Item -Recurse -Force (Join-Path $Desde "*") (Join-Path $Raiz $Carpeta) }
}
Iniciar-Servidor

Write-Host ""
Write-Host "Importación terminada. BORRE ahora $Json (tiene datos personales sin cifrar)." -ForegroundColor Yellow
