<#
.SYNOPSIS
  Полный запуск OryaAgent (Windows / PowerShell 5.1+).

.DESCRIPTION
  Последовательность (локальный режим, по умолчанию):
    1. Проверка, что порты API и UI свободны.
    2. uv sync (зависимости).
    3. docker daemon; при выключенном — автозапуск Docker Desktop
       (отключается флагом -NoDockerStart).
    4. docker compose up -d postgres redis + ожидание pg_isready.
       Хост-порты БД/Redis берутся из POSTGRES_PORT/REDIS_PORT (env или .env),
       а при их отсутствии — из уже запущенного контейнера (без recreate).
       Если порт занят посторонним процессом, а явно не задан — подбирается
       свободный (с +3); явно заданный занятый порт = fail-fast с владельцем.
    5. uv run python -m app.db.migrate (DATABASE_URL выравнивается под порт БД).
    6. Фоновый uvicorn  -> logs/api.log  + logs/api.pid
    7. Ожидание GET /health на порту API.
    8. Фоновый Chainlit -> logs/ui.log   + logs/ui.pid
       (ORYA_API_URL указывает на запущенный API).
    9. Ожидание ответа на порту UI.

  Режим -Stack: вместо шагов 2/5-9 полный контейнерный стек
  `docker compose --profile app --profile observability up -d --build`
  (без ../OryaObservability — деградация до профиля app) + ожидание
  health-чеков API/UI строго, Langfuse — best-effort.

  Логи: logs/api.log, logs/api.err.log, logs/ui.log, logs/ui.err.log
  Остановка: scripts/stop.ps1 (снимает и локальные процессы, и весь стек)

.PARAMETER SkipSync
  Пропустить `uv sync` (зависимости уже установлены).

.PARAMETER Reload
  Запустить uvicorn с --reload (авто-reload при изменении файлов).

.PARAMETER Stack
  Полный контейнерный стек (api + chainlit + observability) вместо
  локальных процессов; uv sync/миграции/спавн не выполняются.

.PARAMETER NoDockerStart
  Не пытаться автозапускать Docker Desktop при выключенном демоне.

.PARAMETER ApiPort
  Порт API (по умолчанию $env:API_PORT, иначе 8000).
  В режиме -Stack экспортируется в compose (${API_PORT:-8000}).

.PARAMETER UiPort
  Порт UI (по умолчанию $env:CHAINLIT_PORT, иначе 8001).
  В режиме -Stack экспортируется в compose (${CHAINLIT_PORT:-8001}).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -SkipSync -Reload
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -ApiPort 8002
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Stack
#>
[CmdletBinding()]
param(
    [switch]$SkipSync,
    [switch]$Reload,
    [switch]$Stack,
    [switch]$NoDockerStart,
    [int]$ApiPort = 0,
    [int]$UiPort = 0
)

$ErrorActionPreference = 'Stop'

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
$RuntimeFile = Join-Path $Logs 'runtime.env'
$LockFile = Join-Path $Logs 'start.ps1.lock'
$ApiPidFile = Join-Path $Logs 'api.pid'
$UiPidFile = Join-Path $Logs 'ui.pid'
$ApiLog = Join-Path $Logs 'api.log'
$ApiErrLog = Join-Path $Logs 'api.err.log'
$UiLog = Join-Path $Logs 'ui.log'
$UiErrLog = Join-Path $Logs 'ui.err.log'

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Done([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Stop-Fail([string]$Message) {
    Write-Host "!!  $Message" -ForegroundColor Red
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
    exit 1
}

# Запуск нативной команды, безопасный при $ErrorActionPreference = 'Stop':
# stderr нативных команд при редиректе превращается в ErrorRecord и бросил бы
# исключение — поэтому на время выполнения откатываем EAP на 'Continue'.
# Возвращает код выхода команды; stdout (если не -Quiet) уходит в консоль.
function Invoke-Native {
    param([scriptblock]$Block, [switch]$Quiet)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Quiet) { & $Block *> $null }
        else { & $Block | Out-Host }
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prevEap
    }
}

# Значение KEY из файла вида KEY=value (первое вхождение, без комментариев).
function Get-FileValue([string]$Path, [string]$Key) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=\s*(.*?)\s*$") {
            $value = $Matches[1]
            if ($value -and -not $value.StartsWith('#')) { return $value }
        }
    }
    return $null
}

# Значение KEY из .env репозитория (env-переменные имеют приоритет сами по себе).
function Get-EnvFileValue([string]$Key) {
    return Get-FileValue (Join-Path $Root '.env') $Key
}

# Хост-порт контейнера: docker port <container> <spec> -> 5435 | $null.
function Get-DockerPort([string]$Container, [string]$PortSpec) {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & docker port $Container $PortSpec 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        foreach ($line in @($out)) {
            if ("$line" -match ':(\d+)\s*$') { return [int]$Matches[1] }
        }
        return $null
    }
    finally {
        $ErrorActionPreference = $prevEap
    }
}

function Get-ListenerPids([int]$Port) {
    @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

function Test-PortBusy([int]$Port) {
    return (Get-ListenerPids $Port).Count -gt 0
}

# Владелец порта: pid + имя процесса (для сообщений об ошибке).
function Get-PortOwner([int]$Port) {
    $pidValue = Get-ListenerPids $Port | Select-Object -First 1
    if (-not $pidValue) { return $null }
    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    $name = if ($proc) { $proc.ProcessName } else { '?' }
    return @{ Pid = [int]$pidValue; Name = $name }
}

# docker-слушатель (docker-proxy / com.docker.backend / wslrelay / vmmem).
function Test-DockerOwner([int]$Port) {
    $owner = Get-PortOwner $Port
    if (-not $owner) { return $false }
    return $owner.Name -match 'docker|vmmem|wslrelay'
}

# Свободный порт начиная с $From (диапазон 30 попыток) либо $null.
function Get-FreePort([int]$From) {
    for ($p = $From; $p -lt ($From + 30); $p++) {
        if (-not (Test-PortBusy $p)) { return $p }
    }
    return $null
}

function Wait-Http {
    param(
        [string]$Url,
        [int]$TimeoutS,
        [string]$What,
        [switch]$Optional  # best-effort: таймаут = предупреждение, не ошибка
    )
    $deadline = (Get-Date).AddSeconds($TimeoutS)
    while ((Get-Date) -lt $deadline) {
        try {
            $null = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            return $true
        }
        catch {
            Start-Sleep -Milliseconds 1000
        }
    }
    if ($Optional) {
        Write-Host "!!  Таймаут ${TimeoutS}s: $What ($Url) не ответил — продолжаю без него" -ForegroundColor Yellow
        return $false
    }
    Write-Host "!!  Таймаут ${TimeoutS}s: $What ($Url) не ответил" -ForegroundColor Red
    return $false
}

function Show-LogTail([string]$Path, [int]$Lines = 40) {
    if (Test-Path -LiteralPath $Path) {
        Write-Host "--- последние строки $Path ---" -ForegroundColor Yellow
        Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Host "    $_" }
        Write-Host "--- конец ---" -ForegroundColor Yellow
    }
}

# --- 0. Lock от параллельного запуска ----------------------------------------
# Два одновременных start дают два uvicorn и гонку за pid-файлы. После жёсткого
# убийства процесса остаточный лок чистится по несуществующему pid.
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
if (Test-Path -LiteralPath $LockFile) {
    $lockRaw = (Get-Content -LiteralPath $LockFile -Raw -ErrorAction SilentlyContinue)
    $lockPid = 0
    if ($lockRaw -and $lockRaw.Trim() -match '^\d+$') { $lockPid = [int]$lockRaw.Trim() }
    if ($lockPid -gt 0 -and (Get-Process -Id $lockPid -ErrorAction SilentlyContinue)) {
        Stop-Fail "start уже выполняется (pid $lockPid) — дождитесь завершения или запустите scripts\stop.ps1"
    }
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}
Set-Content -LiteralPath $LockFile -Value $PID -Encoding ascii

# --- 1. Повторный запуск? ----------------------------------------------------
Write-Step "Проверка портов ($ApiPort API / $UiPort UI)"
if (Test-PortBusy $ApiPort) {
    if (Test-DockerOwner $ApiPort) {
        Stop-Fail "Порт $ApiPort занят контейнером Docker — похоже, стек уже поднят. Остановите: scripts\stop.ps1"
    }
    Stop-Fail "Порт $ApiPort уже занят — агент, похоже, уже запущен. Остановите: scripts\stop.ps1"
}
if (Test-PortBusy $UiPort) {
    if (Test-DockerOwner $UiPort) {
        Stop-Fail "Порт $UiPort занят контейнером Docker — похоже, стек уже поднят. Остановите: scripts\stop.ps1"
    }
    Stop-Fail "Порт $UiPort уже занят — UI, похоже, уже запущен. Остановите: scripts\stop.ps1"
}
Write-Done "порты свободны"

# --- 1. Зависимости ---------------------------------------------------------
# В режиме -Stack всё крутится в контейнерах: uv sync и .venv не нужны.
if ($Stack) {
    Write-Step "Режим -Stack: uv sync / локальный venv пропущены"
}
else {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Stop-Fail "uv не найден в PATH — установите: https://docs.astral.sh/uv/"
    }
    if (-not $SkipSync) {
        Write-Step "uv sync"
        $syncCode = Invoke-Native { uv sync }
        if ($syncCode -ne 0) { Stop-Fail "uv sync завершился с кодом $syncCode" }
        Write-Done "зависимости установлены"
    }
    else {
        Write-Step "uv sync пропущен (-SkipSync)"
    }

    # Python из venv: модули запускаем напрямую (`python -m ...`), минуя
    # console-script .exe-лаунчеры — при старте через Start-Process они не
    # наследуют stdout/stderr, и логи в logs/*.log остаются пустыми.
    $PyExe = Join-Path $Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $PyExe)) {
        Stop-Fail ".venv не найден: $PyExe — запустите без -SkipSync, чтобы выполнить uv sync"
    }
}

# --- 2. Docker daemon (+ автозапуск) ----------------------------------------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-Fail "docker CLI не найден в PATH — установите Docker Desktop"
}
Write-Step "Docker daemon"
$dockerCode = Invoke-Native { docker info --format "{{.ServerVersion}}" } -Quiet
if ($dockerCode -ne 0) {
    if ($NoDockerStart) {
        Stop-Fail "Docker недоступен (-NoDockerStart) — запустите Docker Desktop и повторите запуск"
    }
    $ddExe = Join-Path ${env:ProgramFiles} 'Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path -LiteralPath $ddExe)) {
        Stop-Fail "Docker недоступен, Docker Desktop не найден ($ddExe) — запустите его вручную"
    }
    Write-Step "Docker daemon не запущен — стартую Docker Desktop (до 120s, -NoDockerStart отключает)"
    Start-Process -FilePath $ddExe -WindowStyle Hidden | Out-Null
    $ddDeadline = (Get-Date).AddSeconds(120)
    $dockerCode = 1
    while ((Get-Date) -lt $ddDeadline) {
        Start-Sleep -Seconds 3
        $dockerCode = Invoke-Native { docker info --format "{{.ServerVersion}}" } -Quiet
        if ($dockerCode -eq 0) { break }
    }
    if ($dockerCode -ne 0) {
        Stop-Fail "Docker не поднялся за 120s — запустите Docker Desktop вручную и повторите"
    }
    Write-Done "Docker Desktop запущен"
}
Write-Done "Docker доступен"

# Хост-порты: env > .env > уже запущенный контейнер > дефолт compose.
# Произведённые значения экспортируются, чтобы `compose up` не пересоздавал
# существующие контейнеры (и чтобы миграции/API попали в тот же порт).
# Фолбэк: занятый порт, не являющийся нашим контейнером, при непрямом
# источнике (дефолт/runtime.env) → подбор свободного с +3; при явном
# источнике (env/.env) → fail-fast с именем владельца.
$PgExplicit = $false
$RedisExplicit = $false
$PgPort = $null
$RedisPort = $null
if ($env:POSTGRES_PORT) { $PgPort = [int]$env:POSTGRES_PORT; $PgExplicit = $true }
elseif ($envFilePg = Get-EnvFileValue 'POSTGRES_PORT') { $PgPort = [int]$envFilePg; $PgExplicit = $true }
else {
    $detected = Get-DockerPort 'oryaagent-postgres-1' '5432/tcp'
    if (-not $detected) { $detected = Get-FileValue $RuntimeFile 'POSTGRES_PORT' }
    if ($detected) {
        $PgPort = [int]$detected
        $env:POSTGRES_PORT = "$PgPort"
        Write-Step "POSTGRES_PORT не задан — использую порт из запуска/контейнера: $PgPort"
    }
}
if ($env:REDIS_PORT) { $RedisPort = [int]$env:REDIS_PORT; $RedisExplicit = $true }
elseif ($envFileRedis = Get-EnvFileValue 'REDIS_PORT') { $RedisPort = [int]$envFileRedis; $RedisExplicit = $true }
else {
    $detected = Get-DockerPort 'oryaagent-redis-1' '6379/tcp'
    if (-not $detected) { $detected = Get-FileValue $RuntimeFile 'REDIS_PORT' }
    if ($detected) {
        $RedisPort = [int]$detected
        $env:REDIS_PORT = "$RedisPort"
        Write-Step "REDIS_PORT не задан — использую порт из запуска/контейнера: $RedisPort"
    }
}
$PgResolved = 5432
if ($PgPort) { $PgResolved = $PgPort }
$RedisResolved = 6379
if ($RedisPort) { $RedisResolved = $RedisPort }

# Занятость: если порт публикует наш контейнер — это он и есть (compose не
# пересоздаёт); иначе чужой слушатель. Явный порт чужим процессом = ошибка.
function Resolve-HostPort {
    param([int]$Port, [string]$Key, [string]$Container, [string]$Spec, [bool]$Explicit)
    $ours = Get-DockerPort $Container $Spec
    if ($ours -and $ours -eq $Port) { return $Port }  # наш контейнер уже на этом порту
    if (-not (Test-PortBusy $Port)) { return $Port }
    $owner = Get-PortOwner $Port
    $ownerDesc = "?"
    if ($owner) { $ownerDesc = "$($owner.Name) (pid $($owner.Pid))" }
    if ($Explicit) {
        Stop-Fail "$Key=$Port задан явно, но занят посторонним процессом $ownerDesc — освободите порт или задайте другой"
    }
    $free = Get-FreePort ($Port + 3)
    if (-not $free) {
        Stop-Fail "$Key=$Port занят ($ownerDesc), свободных в диапазоне +30 не найдено"
    }
    Write-Step "$Key=$Port занят ($ownerDesc) — подбираю свободный: $free"
    Set-Item -Path "env:$Key" -Value "$free"
    return $free
}
$PgResolved = Resolve-HostPort -Port $PgResolved -Key 'POSTGRES_PORT' `
    -Container 'oryaagent-postgres-1' -Spec '5432/tcp' -Explicit:$PgExplicit
$RedisResolved = Resolve-HostPort -Port $RedisResolved -Key 'REDIS_PORT' `
    -Container 'oryaagent-redis-1' -Spec '6379/tcp' -Explicit:$RedisExplicit

# Запоминаем выбранные порты ДО compose up: после `docker compose down`
# контейнеров нет, но следующий запуск должен поднять их на тех же
# хост-портах; при падении up выбор тоже сохраняется.
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
Set-Content -LiteralPath $RuntimeFile `
    -Value "POSTGRES_PORT=$PgResolved`nREDIS_PORT=$RedisResolved" -Encoding ascii

if ($Stack) {
    # --- Режим -Stack: полный контейнерный стек ----------------------------
    if ($SkipSync) { Write-Step "-SkipSync не нужен в режиме -Stack (uv sync и так пропущен)" }
    if ($Reload) { Write-Host "!!  -Reload не действует в режиме -Stack (контейнеры)" -ForegroundColor Yellow }
    $Profiles = @('--profile', 'app')
    $sibling = Join-Path (Split-Path -Parent $Root) 'OryaObservability'
    if (Test-Path -LiteralPath $sibling) {
        $Profiles += @('--profile', 'observability')
    }
    else {
        Write-Host "!!  $sibling не найден — профиль observability пропущен (только app)" -ForegroundColor Yellow
    }
    # Порты API/UI тоже уходят в compose (${API_PORT:-8000} / ${CHAINLIT_PORT:-8001}).
    $env:API_PORT = "$ApiPort"
    $env:CHAINLIT_PORT = "$UiPort"

    Write-Step ("docker compose " + ($Profiles -join ' ') + " up -d --build")
    $composeCode = Invoke-Native { docker compose @Profiles up -d --build }
    if ($composeCode -ne 0) {
        Invoke-Native { docker compose logs --tail 60 } | Out-Null
        Stop-Fail "docker compose up завершился с кодом $composeCode (логи выше)"
    }

    Write-Step "Ожидание Postgres (pg_isready)"
    $pgDeadline = (Get-Date).AddSeconds(60)
    $pgReady = $false
    while ((Get-Date) -lt $pgDeadline) {
        $pgCode = Invoke-Native { docker compose exec -T postgres pg_isready -U orya -d orya_sessions } -Quiet
        if ($pgCode -eq 0) { $pgReady = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $pgReady) { Stop-Fail "Postgres не стал готов за 60s (docker compose logs postgres)" }
    Write-Done "Postgres готов"

    if (-not (Wait-Http "http://127.0.0.1:$ApiPort/health" 180 "API")) {
        Invoke-Native { docker compose logs --tail 60 api } | Out-Null
        Stop-Fail "API не ответил /health — подробности в логах выше"
    }
    Write-Done "API здоров: http://127.0.0.1:$ApiPort/health"
    if (-not (Wait-Http "http://127.0.0.1:$UiPort/" 120 "Chainlit")) {
        Invoke-Native { docker compose logs --tail 60 chainlit } | Out-Null
        Stop-Fail "UI не ответил — подробности в логах выше"
    }
    Write-Done "UI доступен: http://127.0.0.1:$UiPort/"
    if ($Profiles -contains 'observability') {
        # Langfuse v3 поднимается долго (миграции ClickHouse/Postgres) — best-effort.
        $null = Wait-Http "http://127.0.0.1:3000/api/public/health" 120 "Langfuse" -Optional
    }

    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "OryaAgent запущен (режим -Stack, контейнеры)" -ForegroundColor Green
    Write-Host "  API        : http://127.0.0.1:$ApiPort/health"
    Write-Host "  UI         : http://127.0.0.1:$UiPort/"
    if ($Profiles -contains 'observability') {
        Write-Host "  Langfuse   : http://127.0.0.1:3000/"
        Write-Host "  Prometheus : http://127.0.0.1:9090/"
        Write-Host "  Sampler    : http://127.0.0.1:4321/sampler/status"
    }
    Write-Host "  Логи       : docker compose logs -f"
    Write-Host "  Стоп       : scripts\stop.ps1"
    exit 0
}

Write-Step "docker compose up -d postgres redis"
$composeCode = Invoke-Native { docker compose up -d postgres redis }
if ($composeCode -ne 0) { Stop-Fail "docker compose up завершился с кодом $composeCode" }

Write-Step "Ожидание готовности Postgres (pg_isready)"
$pgDeadline = (Get-Date).AddSeconds(60)
$pgReady = $false
while ((Get-Date) -lt $pgDeadline) {
    $pgCode = Invoke-Native { docker compose exec -T postgres pg_isready -U orya -d orya_sessions } -Quiet
    if ($pgCode -eq 0) { $pgReady = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $pgReady) { Stop-Fail "Postgres не стал готов за 60s (docker compose logs postgres)" }
Write-Done "Postgres готов"

# --- 3. URL'ы БД/Redis (env > .env > дефолт под фактический порт) -----------
$envDbUrl = $env:DATABASE_URL
$fileDbUrl = Get-EnvFileValue 'DATABASE_URL'
if (-not $envDbUrl -and -not $fileDbUrl) {
    $env:DATABASE_URL = "postgresql://orya:orya_password@localhost:$PgResolved/orya_sessions"
    if ($PgResolved -ne 5432) {
        Write-Step "DATABASE_URL -> localhost:$PgResolved (порт контейнера)"
    }
}
elseif ($PgResolved -ne 5432) {
    $configured = if ($envDbUrl) { $envDbUrl } else { $fileDbUrl }
    if ($configured -match ':(\d+)/' -and [int]$Matches[1] -ne $PgResolved) {
        Write-Host "!!  DATABASE_URL указывает на порт $($Matches[1]), а контейнер БД на $PgResolved — миграции/API могут не достучаться" -ForegroundColor Yellow
    }
}
if (-not $env:REDIS_URL -and -not (Get-EnvFileValue 'REDIS_URL')) {
    $env:REDIS_URL = "redis://localhost:$RedisResolved"
    if ($RedisResolved -ne 6379) {
        Write-Step "REDIS_URL -> localhost:$RedisResolved (порт контейнера)"
    }
}

# --- 4. Миграции ------------------------------------------------------------
Write-Step "Миграции БД (python -m app.db.migrate)"
$migrateCode = Invoke-Native { uv run python -m app.db.migrate }
if ($migrateCode -ne 0) { Stop-Fail "Миграции завершились с кодом $migrateCode" }
Write-Done "схема актуальна"

# --- 5. API (uvicorn) -------------------------------------------------------
Write-Step "Запуск API (uvicorn, порт $ApiPort)"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
Remove-Item -LiteralPath $ApiPidFile, $UiPidFile, $ApiLog, $ApiErrLog, $UiLog, $UiErrLog `
    -Force -ErrorAction SilentlyContinue

# PYTHONUNBUFFERED — иначе stdout uvicorn/chainlit блок-буферизуется в файл и
# logs/*.log остаются пустыми до выхода процесса; PYTHONIOENCODING — кириллица
# в логах пишется в UTF-8, а не в кодовой странице консоли. Наследуются детьми.
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'

$pyArgs = @('-m', 'uvicorn', 'app.main:app', '--port', "$ApiPort")
if ($Reload) { $pyArgs += '--reload' }

$apiProc = Start-Process -FilePath $PyExe `
    -ArgumentList $pyArgs `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $ApiLog `
    -RedirectStandardError $ApiErrLog `
    -WindowStyle Hidden `
    -PassThru
Set-Content -LiteralPath $ApiPidFile -Value $apiProc.Id -Encoding ascii
Write-Done "API pid=$($apiProc.Id) -> $ApiLog"

if (-not (Wait-Http "http://127.0.0.1:$ApiPort/health" 60 "API /health")) {
    Show-LogTail $ApiErrLog
    Show-LogTail $ApiLog
    Stop-Fail "API не поднялся — подробности в логах выше"
}
Write-Done "API здоров: http://127.0.0.1:$ApiPort/health"

# --- 6. UI (Chainlit) -------------------------------------------------------
# UI ходит в API по ORYA_API_URL — указываем на только что поднятый API.
$apiUrl = "http://127.0.0.1:$ApiPort"
if ($env:ORYA_API_URL -and $env:ORYA_API_URL -ne $apiUrl) {
    Write-Host "!!  ORYA_API_URL=$($env:ORYA_API_URL) не совпадает с портом API $ApiPort — UI может не достучаться" -ForegroundColor Yellow
}
else {
    $env:ORYA_API_URL = $apiUrl
}

Write-Step "Запуск UI (Chainlit, порт $UiPort)"
$uiProc = Start-Process -FilePath $PyExe `
    -ArgumentList @('-m', 'chainlit', 'run', 'app/ui/chainlit_app.py', '--port', "$UiPort") `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $UiLog `
    -RedirectStandardError $UiErrLog `
    -WindowStyle Hidden `
    -PassThru
Set-Content -LiteralPath $UiPidFile -Value $uiProc.Id -Encoding ascii
Write-Done "UI pid=$($uiProc.Id) -> $UiLog"

if (-not (Wait-Http "http://127.0.0.1:$UiPort/" 60 "Chainlit")) {
    Show-LogTail $UiErrLog
    Show-LogTail $UiLog
    Stop-Fail "UI не поднялся — подробности в логах выше; остановка: scripts\stop.ps1"
}
Write-Done "UI доступен: http://127.0.0.1:$UiPort/"

# --- Итог -------------------------------------------------------------------
Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "OryaAgent запущен" -ForegroundColor Green
Write-Host "  API : $apiUrl  (health: /health)"
Write-Host "  UI  : http://127.0.0.1:$UiPort/"
Write-Host "  Логи: $Logs"
Write-Host "  Стоп: scripts\stop.ps1"
