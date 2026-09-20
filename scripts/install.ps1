# Instalador de NeonWhisper (Windows 10/11)
# Copia la app a Archivos de programa, arma su Python, crea NeonWhisper.exe, los accesos directos
# y la registra en Windows para que aparezca (y se desinstale) desde Aplicaciones instaladas.
#
#   -Dir <carpeta>  instala ahi en vez de "C:\Program Files\NeonWhisper"
#   -PerUser        instala en %LOCALAPPDATA%\Programs\NeonWhisper (sin permisos de administrador)
#   -Autostart      arranca con Windows, minimizado en la bandeja
#   -NoLaunch       no abre la app al terminar
param(
    [string]$Dir = "",
    [switch]$PerUser,
    [switch]$Autostart,
    [switch]$NoLaunch,
    [switch]$Elevated
)
$ErrorActionPreference = "Stop"

$AppName = "NeonWhisper"
$Publisher = "Luisart"
$RepoUrl = "https://github.com/Luisartt/NeonWhisper"
$UninstallKey = "Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"
$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$Source = Split-Path -Parent $PSScriptRoot
# Lo que se copia a la carpeta del programa (models\, .venv\ y .python\ no se copian nunca).
$AppFiles = @(
    "neonwhisper", "scripts", "assets", "docs", "pyproject.toml", "uv.lock", "README.md", "LICENSE",
    "Instalar.bat", "Actualizar.bat", "Desinstalar.bat", "NeonWhisper.bat", "NeonWhisper.pyw"
)

function Step($msg) { Write-Host ""; Write-Host "  >> $msg" -ForegroundColor Cyan }
function Note($msg) { Write-Host "     $msg" }
function Done($msg) { Write-Host "     $msg" -ForegroundColor Green }
function Fail($msg) {
    Write-Host ""; Write-Host "  [X] $msg" -ForegroundColor Red; Write-Host ""
    if ($Elevated) { Read-Host "  Presiona Enter para cerrar" }
    exit 1
}

function Get-AppVersion($folder) {
    $file = Join-Path $folder "neonwhisper\__init__.py"
    if (-not (Test-Path $file)) { return "" }
    $match = Select-String -Path $file -Pattern '__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match) { return $match.Matches[0].Groups[1].Value }
    return ""
}

function Test-Writable($path) {
    try {
        if (-not (Test-Path $path)) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
        $probe = Join-Path $path ".neonwhisper-write-test"
        [IO.File]::WriteAllText($probe, "x")
        Remove-Item $probe -Force
        return $true
    } catch { return $false }
}

function Stop-App($folder) {
    Get-Process -Name "$AppName", "pythonw", "python" -ErrorAction SilentlyContinue |
        Where-Object { try { $_.Path -and $_.Path.StartsWith($folder, "OrdinalIgnoreCase") } catch { $false } } |
        ForEach-Object {
            $_.CloseMainWindow() | Out-Null
            Start-Sleep -Milliseconds 400
            if (-not $_.HasExited) { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
        }
}

function Get-PreviousInstall {
    foreach ($hive in @("HKLM:", "HKCU:")) {
        try {
            $key = Get-ItemProperty -Path "$hive\$UninstallKey" -ErrorAction Stop
            if ($key.InstallLocation -and (Test-Path $key.InstallLocation)) { return $key.InstallLocation }
        } catch {}
    }
    # Instalaciones anteriores a la v1.3: solo dejaban rastro en el inicio con Windows.
    try {
        $run = (Get-ItemProperty -Path $RunKey -Name $AppName -ErrorAction Stop).$AppName
        if ($run -match '"([^"]+)"\s+"([^"]+NeonWhisper\.pyw)"') { return (Split-Path -Parent $Matches[2]) }
        if ($run -match '"([^"]+)\\\.venv\\Scripts\\[^"]+\.exe"') { return $Matches[1] }
    } catch {}
    return ""
}

Write-Host ""
Write-Host "  =============================================" -ForegroundColor DarkCyan
Write-Host "     N E O N W H I S P E R   ::   instalador" -ForegroundColor Cyan
Write-Host "  =============================================" -ForegroundColor DarkCyan

if (-not (Test-Path (Join-Path $Source "neonwhisper\__init__.py"))) {
    Fail "Ejecuta este instalador desde la carpeta de NeonWhisper (la que tiene Instalar.bat)."
}
if (-not $Dir) {
    $Dir = if ($PerUser) { Join-Path $env:LOCALAPPDATA "Programs\$AppName" } else { Join-Path $env:ProgramFiles $AppName }
}
$version = Get-AppVersion $Source
Note "Version:  v$version"
Note "Destino:  $Dir"

# --- Permisos ------------------------------------------------------------------
if (-not (Test-Writable $Dir)) {
    if ($Elevated) { Fail "No puedo escribir en $Dir ni siquiera como administrador." }
    Step "Pidiendo permisos de administrador para instalar en $Dir..."
    $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Dir", "`"$Dir`"", "-Elevated")
    if ($Autostart) { $argv += "-Autostart" }
    if ($NoLaunch) { $argv += "-NoLaunch" }
    try {
        Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argv -Wait
    } catch {
        Fail "Sin permisos de administrador no puedo instalar ahi. Usa: Instalar.bat -PerUser"
    }
    exit 0
}
$Target = (Resolve-Path $Dir).Path
$inPlace = $Source.TrimEnd('\') -ieq $Target.TrimEnd('\')

# --- 1. Copiar el programa -----------------------------------------------------
$previous = Get-PreviousInstall
if (-not $inPlace) {
    Step "Copiando NeonWhisper a $Target..."
    Stop-App $Target
    foreach ($item in $AppFiles) {
        $from = Join-Path $Source $item
        if (-not (Test-Path $from)) { continue }
        $to = Join-Path $Target $item
        if (Test-Path $to -PathType Container) { Remove-Item $to -Recurse -Force }
        Copy-Item -Path $from -Destination $to -Recurse -Force
    }
    Get-ChildItem -Path (Join-Path $Target "neonwhisper") -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Done "Archivos copiados"
} else {
    Step "Actualizando la instalacion en $Target"
    Stop-App $Target
}

# --- 2. uv, Python y dependencias ----------------------------------------------
Step "Buscando uv (gestor de Python)..."
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (-not (Test-Path $uv)) {
        Note "Instalando uv desde astral.sh ..."
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    }
    if (-not (Test-Path $uv)) { Fail "No se pudo instalar uv. Revisa tu conexion a internet." }
}
Note "uv: $uv"

Step "Instalando Python 3.12 y dependencias (Whisper, CUDA, interfaz). Puede tardar unos minutos..."
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Target ".python"
Push-Location $Target
try {
    & $uv python install 3.12 --no-bin
    if ($LASTEXITCODE -ne 0) { Fail "No se pudo instalar Python." }
    & $uv sync --python 3.12 --python-preference only-managed
    if ($LASTEXITCODE -ne 0) { Fail "No se pudieron instalar las dependencias." }
} finally { Pop-Location }

$python = Join-Path $Target ".venv\Scripts\python.exe"
$exe = Join-Path $Target ".venv\Scripts\$AppName.exe"
if (-not (Test-Path $exe)) { Fail "No se genero $AppName.exe. Revisa la salida de uv de arriba." }
Done "$AppName.exe listo"

# --- 3. GPU e icono ------------------------------------------------------------
$gpu = $null
try { $gpu = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1) } catch {}
if ($gpu) { Done "GPU detectada: $gpu (Whisper correra en la GPU)" }
else { Note "No se detecto GPU NVIDIA: Whisper usara el CPU (mas lento)." }

$icon = Join-Path $Target "assets\icon.ico"
if (-not (Test-Path $icon)) { & $python (Join-Path $Target "scripts\make_icon.py") }

# --- 4. Modelos de una instalacion anterior ------------------------------------
if ($env:LOCALAPPDATA -and $previous -and $previous -ne $Target) {
    $modelsDir = Join-Path $env:LOCALAPPDATA "$AppName\models"
    $old = Join-Path $previous "models"
    if ((Test-Path $old) -and (Get-ChildItem $old -ErrorAction SilentlyContinue)) {
        Step "Moviendo tus modelos de la instalacion anterior (asi no vuelves a descargarlos)..."
        New-Item -ItemType Directory -Path $modelsDir -Force | Out-Null
        foreach ($m in Get-ChildItem $old -Directory) {
            $dest = Join-Path $modelsDir $m.Name
            if (Test-Path $dest) { continue }
            try { Move-Item -Path $m.FullName -Destination $dest -Force; Done $m.Name }
            catch { Note "No se pudo mover $($m.Name): $_" }
        }
        Note "Puedes borrar la carpeta vieja: $previous"
    }
}

# --- 5. Modelo de Whisper -------------------------------------------------------
Step "Revisando el modelo de Whisper (large-v3-turbo, ~1.6 GB la primera vez)..."
& $python -m neonwhisper.download
if ($LASTEXITCODE -ne 0) { Fail "No se pudo descargar el modelo." }

# --- 6. Accesos directos e inicio con Windows -----------------------------------
Step "Creando accesos directos..."
$shortcutArgs = @{ Dir = $Target }
$inProgramFiles = $env:ProgramFiles -and $Target.StartsWith($env:ProgramFiles, "OrdinalIgnoreCase")
if (-not $PerUser -and $inProgramFiles) { $shortcutArgs.AllUsers = $true }
$keepAutostart = $false
try { $keepAutostart = $null -ne (Get-ItemProperty -Path $RunKey -Name $AppName -ErrorAction Stop) } catch {}
if ($Autostart -or $keepAutostart) { $shortcutArgs.Autostart = $true }
try {
    & (Join-Path $Target "scripts\create_shortcuts.ps1") @shortcutArgs
} catch {
    Note "No se pudieron crear los accesos directos: $_"
    Note "La app igual funciona: $exe"
}

# El inicio con Windows puede haber quedado apuntando a la carpeta anterior: si create_shortcuts
# no llego a reescribirlo, Windows seguiria abriendo la instalacion vieja en cada arranque.
try {
    $current = (Get-ItemProperty -Path $RunKey -Name $AppName -ErrorAction Stop).$AppName
    if ($current -and $current -notlike "*$Target*") {
        Set-ItemProperty -Path $RunKey -Name $AppName -Value "`"$exe`" --minimized"
        Done "Inicio con Windows apuntando a $exe"
    }
} catch {}

# Accesos directos viejos que apuntaban a la carpeta anterior.
if ($previous -and $previous -ne $Target) {
    try {
        $shell = New-Object -ComObject WScript.Shell
        foreach ($dir in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
            $lnk = Join-Path $dir "$AppName.lnk"
            if (Test-Path $lnk) {
                $t = $shell.CreateShortcut($lnk).TargetPath
                if ($t -and $t.StartsWith($previous, "OrdinalIgnoreCase")) { Remove-Item $lnk -Force -ErrorAction SilentlyContinue }
            }
        }
    } catch {}
}

# --- 7. Registrar el programa en Windows ----------------------------------------
Step "Registrando NeonWhisper en Windows..."
$hive = if ($inProgramFiles) { "HKLM:" } else { "HKCU:" }
$key = "$hive\$UninstallKey"
$size = 0
try { $size = [int](((Get-ChildItem $Target -Recurse -File -ErrorAction SilentlyContinue) | Measure-Object Length -Sum).Sum / 1KB) } catch {}
$uninstaller = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Target\scripts\uninstall.ps1`""
$values = [ordered]@{
    DisplayName          = $AppName
    DisplayVersion       = $version
    Publisher            = $Publisher
    DisplayIcon          = "$Target\assets\icon.ico"
    InstallLocation      = $Target
    UninstallString      = $uninstaller
    QuietUninstallString = "$uninstaller -Silent"
    URLInfoAbout         = $RepoUrl
    HelpLink             = $RepoUrl
    InstallDate          = (Get-Date -Format "yyyyMMdd")
    NoModify             = 1
    NoRepair             = 1
    EstimatedSize        = $size
}
try {
    New-Item -Path $key -Force | Out-Null
    foreach ($name in $values.Keys) {
        $type = if ($values[$name] -is [int]) { "DWord" } else { "String" }
        New-ItemProperty -Path $key -Name $name -Value $values[$name] -PropertyType $type -Force | Out-Null
    }
    Done "Aparece en Configuracion > Aplicaciones > Aplicaciones instaladas"
} catch {
    Note "No se pudo registrar el programa en Windows: $_"
    Note "Para desinstalarlo usa Desinstalar.bat en $Target"
}

Write-Host ""
Write-Host "  NeonWhisper v$version instalado en $Target" -ForegroundColor Green
Write-Host "  Atajo por defecto: Ctrl + Alt + Space" -ForegroundColor Cyan
Write-Host "  Para desinstalarlo: Configuracion > Aplicaciones, o Desinstalar.bat" -ForegroundColor Cyan
Write-Host ""
if (-not $NoLaunch) { Start-Process -FilePath $exe -WorkingDirectory $Target }
if ($Elevated) { Read-Host "  Presiona Enter para cerrar" }
