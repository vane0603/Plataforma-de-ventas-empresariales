# SE EJECUTA EN TU COMPUTADOR ACTUAL (el de desarrollo), no en el servidor.
# Saca una copia de los datos, imágenes y firmas para llevarla al servidor:
#
#   powershell -ExecutionPolicy Bypass -File despliegue\windows\exportar_datos.ps1 -Destino E:\migracion
#
# ATENCIÓN: respaldo.json contiene datos personales SIN cifrar. Llévelo en una memoria USB
# (no por correo ni chat) y bórrelo apenas termine la importación.
param([Parameter(Mandatory = $true)][string]$Destino)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "comun.ps1")
Set-Location $Raiz
New-Item -ItemType Directory -Force -Path $Destino | Out-Null

Paso "1/3 Limpiando permisos de modelos que ya no existen"
Manage @("remove_stale_contenttypes", "--include-stale-apps", "--noinput")

Paso "2/3 Exportando datos"
$env:PYTHONUTF8 = "1"
Manage @("dumpdata", "--natural-foreign", "--natural-primary",
         "-e", "contenttypes", "-e", "auth.permission", "-e", "sessions", "-e", "admin.logentry",
         "-o", (Join-Path $Destino "respaldo.json"))

Paso "3/3 Copiando imágenes (media) y firmas (privado)"
foreach ($Carpeta in "media", "privado") {
    $Origen = Join-Path $Raiz $Carpeta
    if (Test-Path $Origen) { Copy-Item -Recurse -Force $Origen (Join-Path $Destino $Carpeta) }
}
Write-Host "Copia lista en $Destino. Llévela al servidor y ejecute importar_datos.ps1." -ForegroundColor Green
