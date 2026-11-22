#!/usr/bin/env bash
#
# Полная остановка OryaAgent (POSIX / Linux / macOS, а также Git Bash на Windows).
#
#   1. Останавливает API, UI и oriahs-mcp по PID-файлам
#      (logs/api.pid, logs/ui.pid, logs/mcp.pid): на Windows — taskkill /T
#      (дерево процессов, покрывает uvicorn reloader и дочерние процессы
#      chainlit), на POSIX — TERM с дожигом KILL.
#   2. docker compose down — останавливает ВСЕ активные docker-compose проекты,
#      которые используют целевые порты (8000/8001/8765), включая проекты
#      из других директорий. Обрабатывает кросс-проектные конфликты портов.
#   3. Дополнительная очистка Docker-контейнеров, которые всё ещё держат
#      целевые порты после compose down.
#   4. Подстраховка: слушатели портов 8000/8001/8765 — python/uv/chainlit/node.
#      Docker-слушатели автоматически останавливаются через docker stop.
#   5. Удаление stale lock-файлов start.*.lock (pid мёртв) и PID-файлов.
#   6. Финальная проверка: убедиться, что все целевые порты действительно
#      свободны.
#
# Каталог logs/ и logs/runtime.env (память портов) остаются.
#
# Использование:
#   scripts/stop.sh [--skip-docker]
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_PORT="${API_PORT:-8000}"
UI_PORT="${CHAINLIT_PORT:-8001}"

LOGS="$ROOT/logs"
PID_FILES=("API:$LOGS/api.pid" "UI:$LOGS/ui.pid" "MCP:$LOGS/mcp.pid")
SKIP_DOCKER=0

case "$(uname -s 2>/dev/null)" in
    MINGW* | MSYS* | CYGWIN*) IS_WINDOWS=1 ;;
    *) IS_WINDOWS=0 ;;
esac

usage() {
    cat <<'EOF'
Полная остановка OryaAgent: API + UI + docker compose down.

Использование:
  scripts/stop.sh [--skip-docker]

  --skip-docker  остановить только процессы API/UI, контейнеры не трогать
  -h, --help     эта справка
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-docker) SKIP_DOCKER=1 ;;
        -h | --help) usage; exit 0 ;;
        *) echo "!!  Неизвестный аргумент: $1 (см. --help)" >&2; exit 1 ;;
    esac
    shift
done

step() { printf '==> %s\n' "$1"; }
done_msg() { printf '    %s\n' "$1"; }
skip_msg() { printf '    %s\n' "$1"; }

# PIDs слушающих портов. На Windows (Git Bash) возвращает Windows-PID.
port_pids() {
    local port="$1"
    if [ "$IS_WINDOWS" = 1 ]; then
        netstat -ano 2>/dev/null |
            awk -v suf=":$port" '$2 ~ suf"$" && /LISTENING/ {print $NF}' |
            sort -u
    elif command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true
    elif command -v ss >/dev/null 2>&1; then
        ss -lptn "sport = :$port" 2>/dev/null |
            sed -n 's/.*pid=\([0-9]\{1,\}\).*/\1/p' | sort -u
    fi
}

proc_name() {
    local pid="$1"
    if [ "$IS_WINDOWS" = 1 ]; then
        powershell -NoProfile -Command "(Get-Process -Id ${pid} -ErrorAction SilentlyContinue).ProcessName" 2>/dev/null || true
    else
        ps -p "$pid" -o comm= 2>/dev/null || true
    fi
}

# Завершение процесса (и его дерева).
kill_tree() {
    local pid="$1"
    if [ "$IS_WINDOWS" = 1 ]; then
        taskkill //PID "$pid" //T //F >/dev/null 2>&1
    else
        kill -TERM "$pid" 2>/dev/null || true
        local i=0
        while [ "$i" -lt 5 ] && kill -0 "$pid" 2>/dev/null; do
            sleep 1
            i=$((i + 1))
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null || true
        fi
    fi
}

kill_tree_quiet() {
    kill_tree "$1" >/dev/null 2>&1 || true
}

# --- 1. Процессы по PID-файлам ----------------------------------------------
for entry in "${PID_FILES[@]}"; do
    label="${entry%%:*}"
    pid_file="${entry#*:}"
    if [ ! -f "$pid_file" ]; then
        skip_msg "$label: PID-файл отсутствует ($pid_file) — не запускался?"
        continue
    fi
    pid_value="$(tr -d '[:space:]' <"$pid_file" 2>/dev/null || true)"
    rm -f "$pid_file"
    case "$pid_value" in
        '' | *[!0-9]*)
            skip_msg "$label: PID-файл пуст или повреждён — удалил"
            continue
            ;;
    esac
    step "$label: остановка pid=$pid_value (дерево процессов)"
    if [ "$IS_WINDOWS" = 1 ]; then
        if taskkill //PID "$pid_value" //T //F >/dev/null 2>&1; then
            done_msg "$label остановлен"
        else
            skip_msg "$label: pid=$pid_value уже не существует"
        fi
    else
        if ! kill -0 "$pid_value" 2>/dev/null; then
            skip_msg "$label: процесс pid=$pid_value уже не существует"
            continue
        fi
        kill_tree_quiet "$pid_value"
        done_msg "$label остановлен"
    fi
done

# --- 2. Docker compose down (весь стек, включая профили) ---------------------
# Без --profile down снимает только postgres/redis и оставляет api/chainlit/
# langfuse висеть на 8000/8001/3000 — поэтому профили указываем явно
# (паритет с make stack-down).
#
# A-10 enhancement: Stop ALL docker-compose projects that might be using
# ports 8000/8001/8765, not just the current project. This handles the case
# where multiple projects (e.g., llm-security-scanner + oriaai) are running
# simultaneously and one project's containers are holding the ports.
if [ "$SKIP_DOCKER" = 1 ]; then
    skip_msg "docker compose пропущен (--skip-docker)"
elif ! command -v docker >/dev/null 2>&1; then
    skip_msg "docker не найден в PATH — контейнеры не останавливались"
elif ! docker info >/dev/null 2>&1; then
    skip_msg "Docker daemon недоступен — контейнеры не останавливались"
else
    # Get list of all docker-compose projects that are running
    step "Поиск активных docker-compose проектов..."
    docker_projects=""
    if compose_ls_output=$(docker compose ls --format json 2>/dev/null); then
        # Parse JSON and extract project names and config files
        docker_projects=$(echo "$compose_ls_output" | python3 -c "
import json
import sys
try:
    data = json.load(sys.stdin)
    for project in data:
        name = project.get('Name', '')
        config_files = project.get('ConfigFiles', [])
        if config_files:
            config_file = config_files[0]
            project_dir = os.path.dirname(config_file)
            print(f'{name}|{project_dir}|{config_file}')
except Exception as e:
    print(f'Error parsing JSON: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null || true)
    fi
    
    # Stop each project that might be using our ports
    if [ -n "$docker_projects" ]; then
        while IFS='|' read -r project_name project_dir config_file; do
            [ -z "$project_name" ] && continue
            
            # Check if this project's containers are using any of our target ports
            project_uses_ports=0
            if project_containers=$(docker compose --file "$config_file" ps --format json 2>/dev/null); then
                # Check if any container is using our ports
                if echo "$project_containers" | grep -q "$API_PORT\|$UI_PORT\|8765"; then
                    project_uses_ports=1
                fi
            fi
            
            # Stop this project if it's using our ports or if it's the current project
            is_current_project=0
            if [ "$project_dir" = "$ROOT" ]; then
                is_current_project=1
            fi
            
            if [ "$is_current_project" = 1 ] || [ "$project_uses_ports" = 1 ]; then
                step "Остановка проекта $project_name ($project_dir)"
                cd "$project_dir" || continue
                if docker compose --profile app --profile observability down; then
                    done_msg "Проект $project_name остановлен"
                else
                    echo "!!  Проект $project_name: docker compose down завершился с кодом $?" >&2
                fi
                cd "$ROOT" || continue
            else
                skip_msg "Проект $project_name не использует целевые порты — пропущен"
            fi
        done <<< "$docker_projects"
    fi
    
    # Additional cleanup: stop any containers that are still holding our ports
    step "Дополнительная очистка контейнеров на целевых портах..."
    for port in "$API_PORT" "$UI_PORT" 8765; do
        containers_on_port=$(docker ps --filter "publish=$port" --format "{{.ID}} {{.Names}} {{.Ports}}" 2>/dev/null || true)
        if [ -n "$containers_on_port" ]; then
            while read -r container_id container_name container_ports; do
                [ -z "$container_id" ] && continue
                step "Остановка контейнера $container_name (ID: $container_id) на порту $port"
                docker stop "$container_id" 2>/dev/null || true
                docker rm "$container_id" 2>/dev/null || true
                done_msg "Контейнер $container_name остановлен и удален"
            done <<< "$containers_on_port"
        fi
    done
fi

# --- 3. Подстраховка: порты ---------------------------------------------------
# Идёт ПОСЛЕ compose down: контейнерные слушатели уже освобождены,
# здесь добиваются только локальные процессы.
# 
# A-10 enhancement: Now also handle Docker processes that might still be
# holding ports after the compose down (e.g., from other projects).
for port in "$API_PORT" "$UI_PORT" 8765; do
    for owner_pid in $(port_pids "$port"); do
        case "$owner_pid" in
            '' | *[!0-9]*) continue ;;
        esac
        name="$(proc_name "$owner_pid")"
        case "$name" in
            *docker* | vmmem | wslrelay)
                skip_msg "порт $port всё ещё занят Docker (${name:-?}, pid=$owner_pid)"
                skip_msg "  Попытка остановить через Docker..."
                
                # Try to find and stop the container that's using this port
                container_id=$(docker ps --filter "publish=$port" --format "{{.ID}}" 2>/dev/null | head -1 || true)
                if [ -n "$container_id" ]; then
                    container_name=$(docker ps --filter "publish=$port" --format "{{.Names}}" 2>/dev/null | head -1 || true)
                    step "Остановка контейнера $container_name (ID: $container_id) на порту $port"
                    docker stop "$container_id" 2>/dev/null || true
                    docker rm "$container_id" 2>/dev/null || true
                    done_msg "Контейнер $container_name остановлен"
                fi
                continue
                ;;
            python* | uv | uvicorn | chainlit | node) ;;
            *)
                skip_msg "порт $port занят посторонним процессом ${name:-?} (pid=$owner_pid) — не трогаю"
                continue
                ;;
        esac
        step "порт $port: остаточный слушатель $name (pid=$owner_pid)"
        kill_tree_quiet "$owner_pid"
        done_msg "pid=$owner_pid остановлен"
    done
done

# --- 4. Stale lock-файлы start.* ---------------------------------------------
# Живой lock (start в процессе) не трогаем — только предупреждаем.
for lock_file in "$LOGS/start.sh.lock" "$LOGS/start.ps1.lock"; do
    [ -f "$lock_file" ] || continue
    lock_pid="$(tr -cd '0-9' <"$lock_file" 2>/dev/null || true)"
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
        echo "!!  $(basename "$lock_file") принадлежит живому процессу pid=$lock_pid — не трогаю" >&2
        continue
    fi
    rm -f "$lock_file"
    skip_msg "удалён stale lock $(basename "$lock_file")"
done

# --- 5. Финальная проверка портов --------------------------------------------
# Убедиться, что целевые порты действительно свободны
step "Финальная проверка портов..."
ports_free=1
for port in "$API_PORT" "$UI_PORT" 8765; do
    if port_pids "$port" | grep -q '[0-9]'; then
        echo "!!  Порт $port всё ещё занят" >&2
        for owner_pid in $(port_pids "$port"); do
            name="$(proc_name "$owner_pid")"
            echo "    - ${name:-?} (PID: $owner_pid)" >&2
        done
        ports_free=0
    else
        done_msg "Порт $port свободен"
    fi
done

echo
if [ "$ports_free" = 1 ]; then
    echo "OryaAgent остановлен — все целевые порты свободны"
else
    echo "OryaAgent остановлен — некоторые порты всё ещё заняты (см. выше)" >&2
fi
