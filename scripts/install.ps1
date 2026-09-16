# Instalador de NeonWhisper (Windows 10/11)
# Instala Python 3.12 dentro de la carpeta, las dependencias, el modelo Whisper y los accesos directos.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host ""; Write-Host "  >> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "  [X] $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  =============================================" -ForegroundColor DarkCyan
Write-Host "     N E O N W H I S P E R   ::   instalador" -ForegroundColor Cyan
Write-Host "  =============================================" -ForegroundColor DarkCyan

# 1. uv (gestor de Python ultrarrapido)
Step "Buscando uv..."
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd) {
    $uv = $uvCmd.Source
} else {
    $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (-not (Test-Path $uv)) {
        Write-Host "     Instalando uv desde astral.sh ..."
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    }
    if (-not (Test-Path $uv)) { Fail "No se pudo instalar uv. Revisa tu conexion a internet." }
}
Write-Host "     uv: $uv"

# 2. Python + dependencias (dentro de la carpeta del proyecto)
Step "Instalando Python 3.12 y dependencias (Whisper, CUDA, interfaz). Puede tardar unos minutos..."
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Root ".python"
& $uv python install 3.12
if ($LASTEXITCODE -ne 0) { Fail "No se pudo instalar Python." }
& $uv sync --python 3.12 --python-preference only-managed
if ($LASTEXITCODE -ne 0) { Fail "No se pudieron instalar las dependencias." }

$python = Join-Path $Root ".venv\Scripts\python.exe"
$pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"

# 3. GPU
$gpu = $null
try { $gpu = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1) } catch {}
if ($gpu) { Write-Host "     GPU detectada: $gpu (Whisper correra en la GPU)" -ForegroundColor Green }
else { Write-Host "     No se detecto GPU NVIDIA: Whisper usara el CPU (mas lento)." -ForegroundColor Yellow }

# 4. Modelo Whisper
Step "Descargando Whisper large-v3-turbo (~1.6 GB, solo la primera vez)..."
& $python -m neonwhisper.download
if ($LASTEXITCODE -ne 0) { Fail "No se pudo descargar el modelo." }

# 5. Icono y accesos directos
Step "Creando accesos directos..."
if (-not (Test-Path (Join-Path $Root "assets\icon.ico"))) { & $python scripts\make_icon.py }
& (Join-Path $PSScriptRoot "create_shortcuts.ps1")

Write-Host ""
Write-Host "  Listo. Abre NeonWhisper desde el escritorio o el menu Inicio." -ForegroundColor Green
Write-Host "  Atajo por defecto: Ctrl + Alt + Space" -ForegroundColor Cyan
Write-Host ""
Start-Process -FilePath $pythonw -ArgumentList "`"$Root\NeonWhisper.pyw`"" -WorkingDirectory $Root
