# Actualizador de NeonWhisper: reemplaza los archivos de la app por los de la ultima version.
# No toca tus modelos (models\), tu entorno de Python (.venv\, .python\) ni tus ajustes e historial
# (%APPDATA%\NeonWhisper).
#
# De donde saca la version nueva, en este orden:
#   1. El .zip que le pases con -Zip
#   2. GitHub, si el repositorio es publico
#   3. El .zip mas reciente de NeonWhisper en tu carpeta Descargas
#      (repositorio privado: entra a GitHub, boton verde Code -> Download ZIP)
#
#   -Root <carpeta>  carpeta donde vive NeonWhisper (si no se pasa, se detecta sola)
#   -Zip <archivo>   usa ese .zip en vez de buscarlo
#   -Branch <rama>   rama de GitHub a instalar (por defecto main)
#   -Force           reinstala aunque ya tengas esa version
param([string]$Root = "", [string]$Zip = "", [string]$Branch = "main", [switch]$Force)
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/Luisartt/NeonWhisper"
# Lo que se reemplaza en cada actualizacion; todo lo demas de la carpeta se queda como esta.
$AppFiles = @(
    "neonwhisper", "scripts", "assets", "docs", "pyproject.toml", "uv.lock", "README.md", "LICENSE",
    "Instalar.bat", "Actualizar.bat", "NeonWhisper.bat", "NeonWhisper.pyw"
)

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

function Test-Install($folder) {
    # Una instalacion de verdad tiene la app y su entorno de Python; una carpeta recien
    # descomprimida tiene la app pero no el entorno, y no hay que actualizarla a ella.
    return (Test-Path (Join-Path $folder "neonwhisper\__init__.py")) -and (Test-Path (Join-Path $folder ".venv"))
}

function Find-Root {
    # 1. La carpeta de la que cuelga este script (el caso normal: scripts\update.ps1).
    if ($PSScriptRoot) {
        $guess = Split-Path -Parent $PSScriptRoot
        if (Test-Install $guess) { return $guess }
    }
    # 2. El inicio con Windows, que apunta al lanzador dentro de la carpeta.
    try {
        $run = Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "NeonWhisper"
        if ($run.NeonWhisper -match '"([^"]*NeonWhisper\.pyw)"') {
            $guess = Split-Path -Parent $Matches[1]
            if (Test-Install $guess) { return $guess }
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

    # --- 3. Reemplazar los archivos de la app -------------------------------------
    Step "Cerrando NeonWhisper si esta abierto..."
    Get-Process -Name pythonw, python -ErrorAction SilentlyContinue |
        Where-Object { try { $_.Path -and $_.Path.StartsWith($Root, "OrdinalIgnoreCase") } catch { $false } } |
        ForEach-Object {
            $_.CloseMainWindow() | Out-Null
            Start-Sleep -Milliseconds 400
            if (-not $_.HasExited) { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
        }

    Step "Copiando los archivos nuevos..."
    foreach ($item in $AppFiles) {
        $from = Join-Path $src.FullName $item
        if (-not (Test-Path $from)) { continue }
        $to = Join-Path $Root $item
        if (Test-Path $to -PathType Container) { Remove-Item $to -Recurse -Force }
        Copy-Item -Path $from -Destination $to -Recurse -Force
        Note $item
    }
    Get-ChildItem -Path (Join-Path $Root "neonwhisper") -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    # --- 4. Dependencias y arranque ------------------------------------------------
    Step "Revisando dependencias..."
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) {
        $local = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
        if (Test-Path $local) { $uv = $local }
    }
    if ($uv) {
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $Root ".python"
        Push-Location $Root
        & $uv sync --python 3.12 --python-preference only-managed
        Pop-Location
        if ($LASTEXITCODE -ne 0) { Fail "No se pudieron instalar las dependencias. Ejecuta Instalar.bat." }
    } else {
        Note "No encontre uv; si la app no abre, ejecuta Instalar.bat."
    }

    $python = Join-Path $Root ".venv\Scripts\python.exe"
    $pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path (Join-Path $Root "assets\icon.ico")) -and (Test-Path $python)) {
        & $python (Join-Path $Root "scripts\make_icon.py")
    }

    Write-Host ""
    Write-Host "  Listo: NeonWhisper v$new" -ForegroundColor Green
    Write-Host "  Tus modelos, ajustes e historial siguen intactos." -ForegroundColor Cyan
    Write-Host ""
    if (Test-Path $pythonw) {
        Start-Process -FilePath $pythonw -ArgumentList "`"$(Join-Path $Root 'NeonWhisper.pyw')`"" -WorkingDirectory $Root
    }
} finally {
    Remove-Item -Path $temp -Recurse -Force -ErrorAction SilentlyContinue
}
