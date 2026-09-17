# Desinstalador de NeonWhisper. Lo llama Windows desde Aplicaciones instaladas, o tu con Desinstalar.bat.
# Quita el programa, sus accesos directos, el inicio con Windows y su registro en Windows.
#
#   -KeepData     conserva ajustes, historial y modelos (no pregunta)
#   -RemoveData   borra tambien ajustes, historial y modelos (no pregunta)
#   -Silent       no pregunta nada; conserva tus datos salvo que se pase -RemoveData
param(
    [string]$Dir = "",
    [switch]$KeepData,
    [switch]$RemoveData,
    [switch]$Silent,
    [switch]$Elevated
)
$ErrorActionPreference = "Stop"

$AppName = "NeonWhisper"
$UninstallKey = "Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"
$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$DataDir = Join-Path $env:APPDATA $AppName        # ajustes, historial, sonidos
$LocalDir = Join-Path $env:LOCALAPPDATA $AppName  # modelos

function Step($msg) { Write-Host ""; Write-Host "  >> $msg" -ForegroundColor Cyan }
function Note($msg) { Write-Host "     $msg" }
function Fail($msg) {
    Write-Host ""; Write-Host "  [X] $msg" -ForegroundColor Red; Write-Host ""
    if (-not $Silent) { Read-Host "  Presiona Enter para cerrar" }
    exit 1
}

function Test-Writable($path) {
    try {
        $probe = Join-Path $path ".neonwhisper-write-test"
        [IO.File]::WriteAllText($probe, "x")
        Remove-Item $probe -Force
        return $true
    } catch { return $false }
}

function Find-Install {
    foreach ($hive in @("HKLM:", "HKCU:")) {
        try {
            $key = Get-ItemProperty -Path "$hive\$UninstallKey" -ErrorAction Stop
            if ($key.InstallLocation -and (Test-Path $key.InstallLocation)) { return $key.InstallLocation }
        } catch {}
    }
    if ($PSScriptRoot) {
        $guess = Split-Path -Parent $PSScriptRoot
        if (Test-Path (Join-Path $guess "neonwhisper\__init__.py")) { return $guess }
    }
    return ""
}

Write-Host ""
Write-Host "  =============================================" -ForegroundColor DarkCyan
Write-Host "     N E O N W H I S P E R   ::   desinstalar" -ForegroundColor Cyan
Write-Host "  =============================================" -ForegroundColor DarkCyan

if (-not $Dir) { $Dir = Find-Install }
if (-not $Dir -or -not (Test-Path $Dir)) { Fail "No encontre la instalacion de NeonWhisper." }
$Dir = (Resolve-Path $Dir).Path
Note "Carpeta: $Dir"

# --- Permisos ------------------------------------------------------------------
if (-not (Test-Writable $Dir)) {
    if ($Elevated) { Fail "No puedo borrar $Dir ni siquiera como administrador." }
    Step "Pidiendo permisos de administrador..."
    $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Dir", "`"$Dir`"", "-Elevated")
    if ($KeepData) { $argv += "-KeepData" }
    if ($RemoveData) { $argv += "-RemoveData" }
    if ($Silent) { $argv += "-Silent" }
    try { Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argv -Wait }
    catch { Fail "Sin permisos de administrador no puedo desinstalarlo." }
    exit 0
}

# --- Que hacer con los datos del usuario ---------------------------------------
$deleteData = [bool]$RemoveData
if (-not $RemoveData -and -not $KeepData -and -not $Silent) {
    Write-Host ""
    Write-Host "  Tus ajustes, tu historial y los modelos de Whisper estan en:" -ForegroundColor Yellow
    Note $DataDir
    Note $LocalDir
    $answer = Read-Host "  Borrarlos tambien? (s = si / Enter = conservarlos)"
    $deleteData = $answer -match '^\s*[sSyY]'
}

# --- Cerrar la app --------------------------------------------------------------
Step "Cerrando NeonWhisper..."
Get-Process -Name "$AppName", "pythonw", "python" -ErrorAction SilentlyContinue |
    Where-Object { try { $_.Path -and $_.Path.StartsWith($Dir, "OrdinalIgnoreCase") } catch { $false } } |
    ForEach-Object {
        $_.CloseMainWindow() | Out-Null
        Start-Sleep -Milliseconds 400
        if (-not $_.HasExited) { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    }
Start-Sleep -Milliseconds 600

# --- Accesos directos e inicio con Windows --------------------------------------
Step "Quitando accesos directos..."
$folders = @(
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("Programs"),
    [Environment]::GetFolderPath("CommonDesktopDirectory"),
    [Environment]::GetFolderPath("CommonPrograms")
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
foreach ($folder in $folders) {
    $lnk = Join-Path $folder "$AppName.lnk"
    if (Test-Path $lnk) { Remove-Item $lnk -Force -ErrorAction SilentlyContinue; Note $lnk }
}
Remove-ItemProperty -Path $RunKey -Name $AppName -ErrorAction SilentlyContinue

# --- Registro de Windows ---------------------------------------------------------
Step "Quitando el registro del programa..."
foreach ($hive in @("HKLM:", "HKCU:")) {
    if (Test-Path "$hive\$UninstallKey") { Remove-Item -Path "$hive\$UninstallKey" -Recurse -Force -ErrorAction SilentlyContinue }
}

# --- Datos del usuario -----------------------------------------------------------
if ($deleteData) {
    Step "Borrando ajustes, historial y modelos..."
    foreach ($folder in @($DataDir, $LocalDir)) {
        if (Test-Path $folder) { Remove-Item $folder -Recurse -Force -ErrorAction SilentlyContinue; Note $folder }
    }
} else {
    Note "Tus ajustes, historial y modelos se quedan en $DataDir y $LocalDir"
}

# --- El programa -----------------------------------------------------------------
Step "Borrando el programa..."
Get-ChildItem -Path $Dir -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -ne $PSScriptRoot } |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host ""
Write-Host "  NeonWhisper desinstalado." -ForegroundColor Green
Write-Host ""
if (-not $Silent) { Read-Host "  Presiona Enter para cerrar" }

# Lo ultimo: borrar la carpeta que contiene a este mismo script, ya sin nadie dentro.
$cleanup = "timeout /t 2 /nobreak >nul & rd /s /q `"$Dir`""
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cleanup -WindowStyle Hidden
