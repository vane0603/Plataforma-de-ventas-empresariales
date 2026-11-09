# Copia de seguridad: base de datos MySQL + imágenes (media) + firmas (privado) en un .zip.
# La tarea "TioCampo - Respaldo" lo ejecuta cada noche. Conserva los últimos 14 días.
#
# Para guardar además una copia en otro disco o en una carpeta sincronizada (OneDrive, Google Drive):
#   respaldo.ps1 -CopiaEn "D:\RespaldosTioCampo"
param(
    [string]$Destino = "C:\TioCampo\respaldos",
    [string]$CopiaEn = "",
    [int]$Dias = 14
)

$ErrorActionPreference = "Stop"
$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

# Lee DB_NAME, DB_USER y DB_PASSWORD del .env.
$Env = @{}
Get-Content (Join-Path $Raiz ".env") | Where-Object { $_ -match "^\s*([A-Z_]+)\s*=(.*)$" } | ForEach-Object {
    $Env[$Matches[1]] = $Matches[2].Trim()
}

$MysqlDump = Get-ChildItem "C:\Program Files\MySQL\MySQL Server*\bin\mysqldump.exe" | Select-Object -Last 1
if (-not $MysqlDump) { throw "No se encontró mysqldump.exe (MySQL Server)." }

New-Item -ItemType Directory -Force -Path $Destino | Out-Null
$Fecha = Get-Date -Format "yyyyMMdd_HHmm"
$Temporal = Join-Path $env:TEMP "tiocampo_respaldo_$Fecha"
New-Item -ItemType Directory -Force -Path $Temporal | Out-Null

# La clave va en un archivo temporal (no en la línea de comandos, que otros procesos pueden ver).
$Credenciales = Join-Path $Temporal "cliente.cnf"
$Host_ = if ($Env['DB_HOST']) { $Env['DB_HOST'] } else { 'localhost' }
$Puerto = if ($Env['DB_PORT']) { $Env['DB_PORT'] } else { '3306' }
"[client]`nuser=$($Env['DB_USER'])`npassword=`"$($Env['DB_PASSWORD'])`"`nhost=$Host_`nport=$Puerto" | Set-Content -Encoding ascii $Credenciales

try {
    $Sql = Join-Path $Temporal "tio_campo.sql"
    $Opciones = @("--defaults-extra-file=$Credenciales", "--single-transaction", "--no-tablespaces", "--routines",
                  "--set-gtid-purged=OFF", "--default-character-set=utf8mb4", "--result-file=$Sql")
    # Versiones nuevas de MySQL intentan copiar "masking policies" (no se usan aquí).
    if ((& $MysqlDump.FullName --help) -match "masking-policies") { $Opciones += "--skip-masking-policies" }
    & $MysqlDump.FullName @Opciones $Env["DB_NAME"]
    if ($LASTEXITCODE -ne 0) { throw "mysqldump terminó con error $LASTEXITCODE." }
    Remove-Item $Credenciales

    foreach ($Carpeta in "media", "privado") {
        $Origen = Join-Path $Raiz $Carpeta
        if (Test-Path $Origen) { Copy-Item -Recurse $Origen (Join-Path $Temporal $Carpeta) }
    }

    $Zip = Join-Path $Destino "tiocampo_$Fecha.zip"
    Compress-Archive -Path (Join-Path $Temporal "*") -DestinationPath $Zip -Force
    if ($CopiaEn) {
        New-Item -ItemType Directory -Force -Path $CopiaEn | Out-Null
        Copy-Item $Zip $CopiaEn
    }

    # Borra respaldos viejos.
    foreach ($Carpeta in @($Destino, $CopiaEn) | Where-Object { $_ }) {
        Get-ChildItem $Carpeta -Filter "tiocampo_*.zip" |
            Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$Dias) } |
            Remove-Item
    }
    Write-Output "Respaldo creado: $Zip"
}
finally {
    Remove-Item -Recurse -Force $Temporal -ErrorAction SilentlyContinue
}
