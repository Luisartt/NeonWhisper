# Actualizador de NeonWhisper: consigue la ultima version y le pasa la instalacion al instalador.
# No toca tus ajustes, tu historial ni tus modelos.
#
# De donde saca la version nueva, en este orden:
#   1. El .zip que le pases con -Zip
#   2. GitHub, si el repositorio es publico
#   3. El .zip mas reciente de NeonWhisper en tu carpeta Descargas
#      (repositorio privado: entra a GitHub, boton verde Code -> Download ZIP)
#
#   -Root <carpeta>  carpeta del programa (si no se pasa, se detecta sola)
#   -Zip <archivo>   usa ese .zip en vez de buscarlo
#   -Branch <rama>   rama de GitHub a instalar (por defecto main)
#   -Force           reinstala aunque ya tengas esa version
param([string]$Root = "", [string]$Zip = "", [string]$Branch = "main", [switch]$Force)
$ErrorActionPreference = "Stop"

$AppName = "NeonWhisper"
$RepoUrl = "https://github.com/Luisartt/NeonWhisper"
$UninstallKey = "Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"
$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

function Step($msg) { Write-Host ""; Write-Host "  >> $msg" -ForegroundColor Cyan }
function Note($msg) { Write-Host "     $msg" }
function Fail($msg) { Write-Host ""; Write-Host "  [X] $msg" -ForegroundColor Red; Write-Host ""; exit 1 }

function Get-AppVersion($folder) {
    $file = Join-Path $folder "neonwhisper\__init__.py"
    if (-not (Test-Path $file)) { return "" }
    $match = Select-String -Path $file -Pattern '__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match) { return $match.Matches[0].Groups[1].Value }
    return ""
}

function Find-Root {
    # 1. Donde Windows tiene registrado el programa.
    foreach ($hive in @("HKLM:", "HKCU:")) {
        try {
            $key = Get-ItemProperty -Path "$hive\$UninstallKey" -ErrorAction Stop
            if ($key.InstallLocation -and (Test-Path $key.InstallLocation)) { return $key.InstallLocation }
        } catch {}
    }
    # 2. La carpeta de la que cuelga este script, si es una instalacion (tiene su entorno de Python).
    if ($PSScriptRoot) {
        $guess = Split-Path -Parent $PSScriptRoot
        if ((Test-Path (Join-Path $guess "neonwhisper\__init__.py")) -and (Test-Path (Join-Path $guess ".venv"))) {
            return $guess
        }
    }
    # 3. Instalaciones anteriores a la v1.3: solo dejaban rastro en el inicio con Windows.
    try {
        $run = (Get-ItemProperty -Path $RunKey -Name $AppName -ErrorAction Stop).$AppName
        if ($run -match '"([^"]+NeonWhisper\.pyw)"') {
            $guess = Split-Path -Parent $Matches[1]
            if (Test-Path (Join-Path $guess "neonwhisper\__init__.py")) { return $guess }
        }
    } catch {}
    return ""
}

function Find-DownloadedZip {
    $folders = @((Join-Path $env:USERPROFILE "Downloads"), (Join-Path $env:USERPROFILE "Descargas")) |
        Where-Object { Test-Path $_ }
    if (-not $folders) { return $null }
    Get-ChildItem -Path $folders -Filter "NeonWhisper*.zip" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

Write-Host ""
Write-Host "  =============================================" -ForegroundColor DarkCyan
Write-Host "     N E O N W H I S P E R   ::   actualizar" -ForegroundColor Cyan
Write-Host "  =============================================" -ForegroundColor DarkCyan

if (-not $Root) { $Root = Find-Root }
if (-not $Root -or -not (Test-Path (Join-Path $Root "neonwhisper\__init__.py"))) {
    Fail "No encontre tu instalacion de NeonWhisper. Ejecuta Actualizar.bat desde su carpeta, o pasa -Root `"C:\ruta\NeonWhisper`"."
}
$Root = (Resolve-Path $Root).Path
Note "Carpeta: $Root"
if (Test-Path (Join-Path $Root ".git")) {
    Fail "Esta carpeta es un clon de git. Actualizala con 'git pull' y luego 'uv sync' (asi no pierdes tu historial de git)."
}

$current = Get-AppVersion $Root
$temp = Join-Path ([IO.Path]::GetTempPath()) ("NeonWhisper-update-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $temp | Out-Null

try {
    # --- 1. Conseguir el .zip de la version nueva ---------------------------------
    $package = ""
    if ($Zip) {
        if (-not (Test-Path $Zip)) { Fail "No existe el archivo $Zip" }
        $package = (Resolve-Path $Zip).Path
        Step "Usando $package"
    } else {
        Step "Descargando la ultima version ($Branch)..."
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
        $package = Join-Path $temp "neonwhisper.zip"
        try {
            Invoke-WebRequest -Uri "$RepoUrl/archive/refs/heads/$Branch.zip" -OutFile $package -UseBasicParsing
        } catch {
            $package = ""
            Note "No se pudo descargar (el repositorio es privado o no hay internet)."
            $found = Find-DownloadedZip
            if ($found) {
                $package = $found.FullName
                Note "Usando el ZIP de tus Descargas: $($found.Name) ($($found.LastWriteTime))"
            }
        }
    }
    if (-not $package) {
        Fail ("No tengo de donde sacar la version nueva.`n" +
              "      Entra a $RepoUrl, boton verde Code -> Download ZIP,`n" +
              "      guardalo en Descargas y vuelve a ejecutar Actualizar.bat`n" +
              "      (o pasale la ruta: Actualizar.bat -Zip `"C:\ruta\NeonWhisper-main.zip`").")
    }

    # --- 2. Comparar versiones ----------------------------------------------------
    $unpacked = Join-Path $temp "nuevo"
    Expand-Archive -Path $package -DestinationPath $unpacked -Force
    $src = Get-ChildItem -Path $unpacked -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "neonwhisper\__init__.py") } | Select-Object -First 1
    if (-not $src) {
        if (Test-Path (Join-Path $unpacked "neonwhisper\__init__.py")) { $src = Get-Item $unpacked }
        else { Fail "Ese .zip no parece ser NeonWhisper." }
    }
    $new = Get-AppVersion $src.FullName
    Note "Instalada: v$current  ->  disponible: v$new"
    if ($new -eq $current -and -not $Force) {
        Write-Host ""
        Write-Host "  Ya tienes la ultima version. Nada que hacer." -ForegroundColor Green
        Write-Host ""
        exit 0
    }

    # --- 3. El instalador de la version nueva hace el resto -------------------------
    # (copia los archivos, revisa dependencias, refresca accesos directos y el registro
    #  de Windows, y pide permisos de administrador solo si la carpeta los necesita)
    & (Join-Path $src.FullName "scripts\install.ps1") -Dir $Root
} finally {
    Remove-Item -Path $temp -Recurse -Force -ErrorAction SilentlyContinue
}
