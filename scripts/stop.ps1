<#
.SYNOPSIS
  Полная остановка OryaAgent (Windows / PowerShell 5.1+).

.DESCRIPTION
  1. Останавливает API, UI и oriahs-mcp по PID-файлам (logs/api.pid,
     logs/ui.pid, logs/mcp.pid) — taskkill /T убивает дерево процессов
     (uvicorn reloader, дочерние chainlit).
  2. docker compose down — останавливает ВСЕ активные docker-compose проекты,
     которые используют целевые порты (8000/8001/8765), включая проекты
     из других директорий. Обрабатывает кросс-проектные конфликты портов.
  3. Дополнительная очистка Docker-контейнеров, которые всё ещё держат
     целевые порты после compose down.
  4. Подстраховка: слушатели портов 8000/8001/8765 (python/uv/chainlit/node).
     Docker-слушатели автоматически останавливаются через docker stop.
  5. Удаление stale lock-файлов start.*.lock (pid мёртв) и PID-файлов.
  6. Финальная проверка: убедиться, что все целевые порты действительно
     свободны.

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
    @{ Name = 'UI'; Path = (Join-Path $Logs 'ui.pid') },
    @{ Name = 'MCP'; Path = (Join-Path $Logs 'mcp.pid') }
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
# 
# A-10 enhancement: Stop ALL docker-compose projects that might be using
# ports 8000/8001/8765, not just the current project. This handles the case
# where multiple projects (e.g., llm-security-scanner + oriaai) are running
# simultaneously and one project's containers are holding the ports.
if ($SkipDocker) {
    Write-Skip "docker compose пропущен (-SkipDocker)"
}
else {
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Skip "Docker daemon недоступен — контейнеры не останавливались"
    }
    else {
        # Get list of all docker-compose projects that are running
        Write-Step "Поиск активных docker-compose проектов..."
        $dockerProjects = @()
        try {
            # Get all running projects with their config files
            $composeLsOutput = & docker compose ls --format json 2>$null
            if ($composeLsOutput) {
                $projects = $composeLsOutput | ConvertFrom-Json
                foreach ($project in $projects) {
                    $configPath = $project.ConfigFiles[0]
                    $projectDir = Split-Path -Parent $configPath
                    $dockerProjects += @{
                        Name = $project.Name
                        Dir = $projectDir
                        ConfigFile = $configPath
                    }
                }
            }
        }
        catch {
            Write-Skip "Не удалось получить список проектов: $($_.Exception.Message)"
        }
        
        # Stop each project that might be using our ports
        foreach ($project in $dockerProjects) {
            # Check if this project's containers are using any of our target ports
            $projectPorts = @()
            try {
                # Get containers for this project
                $projectContainers = & docker compose --file $project.ConfigFile ps --format json 2>$null
                if ($projectContainers) {
                    $containers = $projectContainers | ConvertFrom-Json
                    foreach ($container in $containers) {
                        if ($container.Ports) {
                            foreach ($portMapping in $container.Ports) {
                                if ($portMapping -match "($ApiPort|$UiPort|8765)") {
                                    $projectPorts += $ApiPort
                                    $projectPorts += $UiPort
                                    $projectPorts += 8765
                                    break
                                }
                            }
                        }
                    }
                }
            }
            catch {
                Write-Skip "Не удалось проверить порты проекта $($project.Name): $($_.Exception.Message)"
            }
            
            # Stop this project if it's using our ports or if it's the current project
            $isCurrentProject = ($project.Dir -eq $Root)
            $usesOurPorts = ($projectPorts.Count -gt 0)
            
            if ($isCurrentProject -or $usesOurPorts) {
                Write-Step "Остановка проекта $($project.Name) ($($project.Dir))"
                Set-Location -LiteralPath $project.Dir
                try {
                    & docker compose --profile app --profile observability down
                    if ($LASTEXITCODE -eq 0) {
                        Write-Done "Проект $($project.Name) остановлен"
                    }
                    else {
                        Write-Host "!!  Проект $($project.Name): docker compose down завершился с кодом $LASTEXITCODE" -ForegroundColor Yellow
                    }
                }
                catch {
                    Write-Host "!!  Проект $($project.Name): ошибка остановки: $($_.Exception.Message)" -ForegroundColor Yellow
                }
                Set-Location -LiteralPath $Root
            }
            else {
                Write-Skip "Проект $($project.Name) не использует целевые порты — пропущен"
            }
        }
        
        # Additional cleanup: stop any containers that are still holding our ports
        Write-Step "Дополнительная очистка контейнеров на целевых портах..."
        foreach ($port in @($ApiPort, $UiPort, 8765)) {
            $containersOnPort = & docker ps --filter "publish=$port" --format "{{.ID}} {{.Names}} {{.Ports}}" 2>$null
            if ($containersOnPort) {
                foreach ($containerInfo in $containersOnPort) {
                    $parts = $containerInfo -split ' ', 3
                    if ($parts.Count -ge 2) {
                        $containerId = $parts[0]
                        $containerName = $parts[1]
                        Write-Step "Остановка контейнера $containerName (ID: $containerId) на порту $port"
                        & docker stop $containerId 2>$null
                        & docker rm $containerId 2>$null
                        Write-Done "Контейнер $containerName остановлен и удален"
                    }
                }
            }
        }
    }
}

# --- 3. Подстраховка: порты --------------------------------------------------
# Идёт ПОСЛЕ compose down: контейнерные слушатели уже освобождены,
# здесь добиваются только локальные процессы.
# 
# A-10 enhancement: Now also handle Docker processes that might still be
# holding ports after the compose down (e.g., from other projects).
$ProcessNameFilter = 'python', 'pythonw', 'uv', 'uvicorn', 'chainlit', 'node'
foreach ($Port in @($ApiPort, $UiPort, 8765)) {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($ownerPid in $listeners) {
        $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        
        # Check if this is a Docker-related process
        $isDockerProcess = $proc.ProcessName -match 'docker|vmmem|wslrelay|com\.docker'
        
        if ($isDockerProcess) {
            Write-Skip "порт $Port всё ещё занят Docker ($($proc.ProcessName), pid=$ownerPid)"
            Write-Skip "  Попытка остановить через Docker..."
            
            # Try to find and stop the container that's using this port
            try {
                $containerId = & docker ps --filter "publish=$Port" --format "{{.ID}}" 2>$null | Select-Object -First 1
                if ($containerId) {
                    $containerName = & docker ps --filter "publish=$Port" --format "{{.Names}}" 2>$null | Select-Object -First 1
                    Write-Step "Остановка контейнера $containerName (ID: $containerId) на порту $Port"
                    & docker stop $containerId 2>$null
                    & docker rm $containerId 2>$null
                    Write-Done "Контейнер $containerName остановлен"
                }
            }
            catch {
                Write-Skip "Не удалось остановить Docker-контейнер: $($_.Exception.Message)"
            }
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

# --- 5. Финальная проверка портов --------------------------------------------
# Убедиться, что целевые порты действительно свободны
Write-Step "Финальная проверка портов..."
$portsFree = $true
foreach ($port in @($ApiPort, $UiPort, 8765)) {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        Write-Host "!!  Порт $port всё ещё занят" -ForegroundColor Yellow
        foreach ($listener in $listeners) {
            $proc = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "    - $($proc.ProcessName) (PID: $($listener.OwningProcess))" -ForegroundColor Yellow
            }
        }
        $portsFree = $false
    }
    else {
        Write-Done "Порт $port свободен"
    }
}

Write-Host ""
if ($portsFree) {
    Write-Host "OryaAgent остановлен — все целевые порты свободны" -ForegroundColor Green
}
else {
    Write-Host "OryaAgent остановлен — некоторые порты всё ещё заняты (см. выше)" -ForegroundColor Yellow
}
