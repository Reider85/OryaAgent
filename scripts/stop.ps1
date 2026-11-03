<#
.SYNOPSIS
  Полная остановка OryaAgent (Windows / PowerShell 5.1+).

.DESCRIPTION
  1. Останавливает API и UI по PID-файлам (logs/api.pid, logs/ui.pid) —
     taskkill /T убивает дерево процессов (uvicorn reloader, дочерние chainlit).
  2. docker compose --profile app --profile observability down — снимает
     ВЕСЬ стек: postgres/redis + api/chainlit + langfuse и observability
     (паритет с make stack-down; volume postgres_data сохраняется).
  3. Подстраховка: слушатели портов 8000/8001 (python/uv/chainlit/node;
     docker-слушатели репортятся, но не убиваются).
  4. Удаление stale lock-файлов start.*.lock (pid мёртв) и PID-файлов.

  Каталог logs/ и logs/runtime.env (память портов) остаются.

.PARAMETER SkipDocker
  Остановить только процессы API/UI, контейнеры не трогать.

.PARAMETER ApiPort
  Порт API для подстраховочной проверки слушателей
  (по умолчанию $env:API_PORT, иначе 8000).

.PARAMETER UiPort
  Порт UI (по умолчанию $env:CHAINLIT_PORT, иначе 8001).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
  powershell -ExecutionPolicy Bypass -File scripts\stop.ps1 -SkipDocker
  powershell -ExecutionPolicy Bypass -File scripts\stop.ps1 -ApiPort 8002
#>
[CmdletBinding()]
param(
    [switch]$SkipDocker,
    [int]$ApiPort = 0,
    [int]$UiPort = 0
)

$ErrorActionPreference = 'Continue'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

if ($ApiPort -le 0) {
    $ApiPort = 8000
    if ($env:API_PORT) { $ApiPort = [int]$env:API_PORT }
}
if ($UiPort -le 0) {
    $UiPort = 8001
    if ($env:CHAINLIT_PORT) { $UiPort = [int]$env:CHAINLIT_PORT }
}

$Logs = Join-Path $Root 'logs'
$PidFiles = @(
    @{ Name = 'API'; Path = (Join-Path $Logs 'api.pid') },
    @{ Name = 'UI'; Path = (Join-Path $Logs 'ui.pid') }
)

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Done([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Write-Skip([string]$Message) {
    Write-Host "    $Message" -ForegroundColor DarkYellow
}

function Stop-Tree([int]$ProcessId) {
    & taskkill /PID $ProcessId /T /F *> $null
    return ($LASTEXITCODE -eq 0)
}

# --- 1. Процессы по PID-файлам ---------------------------------------------
foreach ($entry in $PidFiles) {
    $label = $entry.Name
    if (-not (Test-Path -LiteralPath $entry.Path)) {
        Write-Skip "${label}: PID-файл отсутствует ($($entry.Path)) — не запускался?"
        continue
    }
    $raw = (Get-Content -LiteralPath $entry.Path -Raw -ErrorAction SilentlyContinue)
    if (-not $raw -or -not ($raw.Trim() -match '^\d+$')) {
        Write-Skip "${label}: PID-файл пуст или повреждён — удаляю"
        Remove-Item -LiteralPath $entry.Path -Force -ErrorAction SilentlyContinue
        continue
    }
    $pidValue = [int]$raw.Trim()
    $procAlive = $null -ne (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
    if (-not $procAlive) {
        Write-Skip "${label}: процесс pid=$pidValue уже не существует"
        Remove-Item -LiteralPath $entry.Path -Force -ErrorAction SilentlyContinue
        continue
    }
    Write-Step "${label}: остановка pid=$pidValue (дерево процессов)"
    if (Stop-Tree $pidValue) {
        Write-Done "$label остановлен"
    }
    else {
        Write-Host "!!  ${label}: taskkill не смог убить pid=$pidValue" -ForegroundColor Yellow
    }
    Remove-Item -LiteralPath $entry.Path -Force -ErrorAction SilentlyContinue
}

# --- 2. Docker compose down (весь стек, включая профили) --------------------
# Без --profile down снимает только postgres/redis и оставляет api/chainlit/
# langfuse висеть на 8000/8001/3000 — поэтому профили указываем явно
# (паритет с make stack-down).
if ($SkipDocker) {
    Write-Skip "docker compose пропущен (-SkipDocker)"
}
else {
    Write-Step "docker compose --profile app --profile observability down"
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Skip "Docker daemon недоступен — контейнеры не останавливались"
    }
    else {
        & docker compose --profile app --profile observability down
        if ($LASTEXITCODE -eq 0) {
            Write-Done "весь стек остановлен (postgres/redis + app + observability, volume postgres_data сохранён)"
        }
        else {
            Write-Host "!!  docker compose down завершился с кодом $LASTEXITCODE" -ForegroundColor Yellow
        }
    }
}

# --- 3. Подстраховка: порты --------------------------------------------------
# Идёт ПОСЛЕ compose down: контейнерные слушатели уже освобождены,
# здесь добиваются только локальные процессы.
$ProcessNameFilter = 'python', 'pythonw', 'uv', 'uvicorn', 'chainlit', 'node'
foreach ($Port in @($ApiPort, $UiPort)) {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($ownerPid in $listeners) {
        $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        if ($proc.ProcessName -match 'docker|vmmem|wslrelay') {
            Write-Skip "порт $Port всё ещё занят Docker ($($proc.ProcessName), pid=$ownerPid) — контейнер не остановился, см. docker compose ps"
            continue
        }
        if ($ProcessNameFilter -notcontains $proc.ProcessName) {
            Write-Skip "порт $Port занят посторонним процессом $($proc.ProcessName) (pid=$ownerPid) — не трогаю"
            continue
        }
        Write-Step "порт ${Port}: остаточный слушатель $($proc.ProcessName) (pid=$ownerPid)"
        if (Stop-Tree $ownerPid) { Write-Done "pid=$ownerPid остановлен" }
    }
}

# --- 4. Stale lock-файлы start.* --------------------------------------------
# Живой lock (start в процессе) не трогаем — только предупреждаем.
foreach ($lockName in @('start.ps1.lock', 'start.sh.lock')) {
    $lockPath = Join-Path $Logs $lockName
    if (-not (Test-Path -LiteralPath $lockPath)) { continue }
    $lockRaw = (Get-Content -LiteralPath $lockPath -Raw -ErrorAction SilentlyContinue)
    $lockPid = 0
    if ($lockRaw -and $lockRaw.Trim() -match '^\d+$') { $lockPid = [int]$lockRaw.Trim() }
    if ($lockPid -gt 0 -and (Get-Process -Id $lockPid -ErrorAction SilentlyContinue)) {
        Write-Host "!!  $lockName принадлежит живому процессу pid=$lockPid — не трогаю" -ForegroundColor Yellow
        continue
    }
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    Write-Skip "удалён stale lock $lockName"
}

Write-Host ""
Write-Host "OryaAgent остановлен" -ForegroundColor Green
