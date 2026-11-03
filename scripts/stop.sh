#!/usr/bin/env bash
#
# Полная остановка OryaAgent (POSIX / Linux / macOS, а также Git Bash на Windows).
#
#   1. Останавливает API и UI по PID-файлам (logs/api.pid, logs/ui.pid):
#      на Windows — taskkill /T (дерево процессов, покрывает uvicorn reloader
#      и дочерние процессы chainlit), на POSIX — TERM с дожигом KILL.
#   2. docker compose --profile app --profile observability down — снимает
#      ВЕСЬ стек: postgres/redis + api/chainlit + langfuse и observability
#      (паритет с make stack-down; volume postgres_data сохраняется).
#   3. Подстраховка: слушатели портов 8000/8001 — python/uv/chainlit/node;
#      docker-слушатели репортятся, но не убиваются.
#   4. Удаление stale lock-файлов start.*.lock (pid мёртв) и PID-файлов.
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
PID_FILES=("API:$LOGS/api.pid" "UI:$LOGS/ui.pid")
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
if [ "$SKIP_DOCKER" = 1 ]; then
    skip_msg "docker compose пропущен (--skip-docker)"
elif ! command -v docker >/dev/null 2>&1; then
    skip_msg "docker не найден в PATH — контейнеры не останавливались"
elif ! docker info >/dev/null 2>&1; then
    skip_msg "Docker daemon недоступен — контейнеры не останавливались"
else
    step "docker compose --profile app --profile observability down"
    if docker compose --profile app --profile observability down; then
        done_msg "весь стек остановлен (postgres/redis + app + observability, volume postgres_data сохранён)"
    else
        echo "!!  docker compose down завершился с кодом $?" >&2
    fi
fi

# --- 3. Подстраховка: порты ---------------------------------------------------
# Идёт ПОСЛЕ compose down: контейнерные слушатели уже освобождены,
# здесь добиваются только локальные процессы.
for port in "$API_PORT" "$UI_PORT"; do
    for owner_pid in $(port_pids "$port"); do
        case "$owner_pid" in
            '' | *[!0-9]*) continue ;;
        esac
        name="$(proc_name "$owner_pid")"
        case "$name" in
            *docker* | vmmem | wslrelay)
                skip_msg "порт $port всё ещё занят Docker (${name:-?}, pid=$owner_pid) — контейнер не остановился, см. docker compose ps"
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

echo
echo "OryaAgent остановлен"
