#!/usr/bin/env bash
#
# Полный запуск OryaAgent (POSIX / Linux / macOS, а также Git Bash на Windows).
#
# Последовательность (локальный режим, по умолчанию):
#   1. Проверка, что порты API (8000) и UI (8001) свободны.
#   2. uv sync (зависимости).
#   3. Docker daemon; при выключенном — автозапуск (Docker Desktop /
#      systemctl / open -a Docker), отключается --no-docker-start.
#   4. docker compose up -d postgres redis + ожидание pg_isready.
#      Занятый хост-порт БД/Redis при непрямом источнике (дефолт/runtime.env)
#      → подбор свободного с +3; явно заданный занятый = fail с владельцем.
#   5. uv run python -m app.db.migrate (идемпотентно).
#   6. Фоновый uvicorn   -> logs/api.log + logs/api.pid
#   7. Ожидание GET /health на :8000.
#   8. Фоновый Chainlit  -> logs/ui.log  + logs/ui.pid
#   9. Ожидание ответа на :8001.
#
# Режим --stack: вместо шагов 2/5-9 полный контейнерный стек
# `docker compose --profile app --profile observability up -d --build`
# (без ../OryaObservability — деградация до профиля app) + health-ожидания.
#
# Логи:    logs/api.log, logs/api.err.log, logs/ui.log, logs/ui.err.log
# Остановка: scripts/stop.sh (снимает и локальные процессы, и весь стек)
#
# Использование:
#   scripts/start.sh [--skip-sync] [--reload] [--stack] [--no-docker-start]
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_PORT="${API_PORT:-8000}"
UI_PORT="${CHAINLIT_PORT:-8001}"

LOGS="$ROOT/logs"
RUNTIME_FILE="$LOGS/runtime.env"
API_PID_FILE="$LOGS/api.pid"
UI_PID_FILE="$LOGS/ui.pid"
API_LOG="$LOGS/api.log"
API_ERR_LOG="$LOGS/api.err.log"
UI_LOG="$LOGS/ui.log"
UI_ERR_LOG="$LOGS/ui.err.log"

SKIP_SYNC=0
RELOAD=0
STACK=0
NO_DOCKER_START=0

case "$(uname -s 2>/dev/null)" in
    MINGW* | MSYS* | CYGWIN*) IS_WINDOWS=1 ;;
    *) IS_WINDOWS=0 ;;
esac

usage() {
    cat <<'EOF'
Полный запуск OryaAgent: uv sync -> docker compose (postgres/redis)
-> миграции -> API (uvicorn, :8000) -> UI (Chainlit, :8001).

Использование:
  scripts/start.sh [--skip-sync] [--reload] [--stack] [--no-docker-start]

  --skip-sync        пропустить uv sync (зависимости уже установлены)
  --reload           запустить uvicorn с --reload
  --stack            полный контейнерный стек (api + chainlit +
                     observability) вместо локальных процессов;
                     uv sync/миграции/спавн не выполняются
  --no-docker-start  не пытаться автозапускать Docker при выключенном демоне
  -h, --help         эта справка

Переменные окружения:
  API_PORT       порт API       (по умолчанию 8000)
  CHAINLIT_PORT  порт UI        (по умолчанию 8001)
  POSTGRES_PORT, REDIS_PORT     хост-порты БД/Redis (иначе из .env
                                или из уже запущенного контейнера;
                                занятый чужой порт → подбор свободного)
  DATABASE_URL, REDIS_URL       URL'ы; задаются автоматически под порт

Логи:    logs/api.log, logs/api.err.log, logs/ui.log, logs/ui.err.log
Остановка: scripts/stop.sh
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-sync) SKIP_SYNC=1 ;;
        --reload) RELOAD=1 ;;
        --stack) STACK=1 ;;
        --no-docker-start) NO_DOCKER_START=1 ;;
        -h | --help) usage; exit 0 ;;
        *) echo "!!  Неизвестный аргумент: $1 (см. --help)" >&2; exit 1 ;;
    esac
    shift
done

step() { printf '==> %s\n' "$1"; }
done_msg() { printf '    %s\n' "$1"; }
fail() { printf '!!  %s\n' "$1" >&2; exit 1; }

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

port_busy() {
    [ -n "$(port_pids "$1")" ]
}

# Имя процесса-владельца порта (для сообщений об ошибке).
proc_name() {
    local pid="$1"
    if [ "$IS_WINDOWS" = 1 ]; then
        powershell -NoProfile -Command "(Get-Process -Id ${pid} -ErrorAction SilentlyContinue).ProcessName" 2>/dev/null || true
    else
        ps -p "$pid" -o comm= 2>/dev/null || true
    fi
}

# docker-слушатель (docker-proxy / com.docker.backend / wslrelay / vmmem).
port_is_docker() {
    local pid name
    for pid in $(port_pids "$1"); do
        name="$(proc_name "$pid")"
        case "$name" in
            *docker* | vmmem | wslrelay) return 0 ;;
        esac
    done
    return 1
}

# Первый свободный порт начиная с $1 (30 попыток) либо пусто.
free_port_from() {
    local start="$1" p i=0
    p="$start"
    while [ "$i" -lt 30 ]; do
        if ! port_busy "$p"; then
            echo "$p"
            return 0
        fi
        p=$((p + 1))
        i=$((i + 1))
    done
    return 0
}

http_ok() {
    local url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -fsS -m 3 -o /dev/null "$url" 2>/dev/null
    else
        uv run python - "$url" <<'PY' 2>/dev/null
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=3).read(1)
PY
    fi
}

wait_http() {
    local url="$1" timeout="$2" what="$3" optional="${4:-0}" i=0
    while [ "$i" -lt "$timeout" ]; do
        if http_ok "$url"; then
            return 0
        fi
        sleep 1
        i=$((i + 1))
    done
    if [ "$optional" = 1 ]; then
        printf '!!  Таймаут %ss: %s (%s) не ответил — продолжаю без него\n' \
            "$timeout" "$what" "$url" >&2
        return 1
    fi
    printf '!!  Таймаут %ss: %s (%s) не ответил\n' "$timeout" "$what" "$url" >&2
    return 1
}

show_log_tail() {
    if [ -f "$1" ]; then
        printf -- '--- последние строки %s ---\n' "$1" >&2
        tail -n 40 "$1" >&2 || true
        printf -- '--- конец ---\n' "$1" >&2
    fi
}

# Фоновый запуск: записывает PID в файл, stdout/stderr в логи.
# На Windows поднимает процесс через powershell Start-Process (-WindowStyle Hidden),
# чтобы он пережил закрытие окна терминала; иначе — nohup.
spawn_bg() {
    local out="$1" err="$2" pidf="$3" exe="$4"
    shift 4
    local pid
    if [ "$IS_WINDOWS" = 1 ]; then
        local alist="" a
        for a in "$@"; do alist="${alist}'${a}',"; done
        alist="${alist%,}"
        local win_exe win_root win_out win_err win_pidf spawn_log
        win_exe="$(cygpath -w "$exe" 2>/dev/null || echo "$exe")"
        win_root="$(pwd -W)"
        win_out="$(cygpath -w "$out" 2>/dev/null || echo "$out")"
        win_err="$(cygpath -w "$err" 2>/dev/null || echo "$err")"
        win_pidf="$(cygpath -w "$pidf" 2>/dev/null || echo "$pidf")"
        spawn_log="${pidf%.pid}.spawn.log"
        # PYTHONUNBUFFERED — иначе stdout uvicorn/chainlit блок-буферизуется в
        # файл и logs/*.log остаются пустыми до выхода процесса; PYTHONIOENCODING
        # — кириллица в логах пишется в UTF-8, а не в кодовой странице консоли.
        # PID пишем в файл, а не в stdout: stdout-пайп powershell наследуется
        # внуком (python), и подстановка $(...) никогда не дождалась бы EOF —
        # старт завис бы после создания процесса. Сюда же уходит bootstrap-ошибка.
        : >"$spawn_log"
        powershell -NoProfile -Command "\$env:PYTHONUNBUFFERED='1'; \$env:PYTHONIOENCODING='utf-8'; \$p = Start-Process -FilePath '${win_exe}' -ArgumentList @(${alist}) -WorkingDirectory '${win_root}' -RedirectStandardOutput '${win_out}' -RedirectStandardError '${win_err}' -WindowStyle Hidden -PassThru; Set-Content -LiteralPath '${win_pidf}' -Value \$p.Id -Encoding ascii" \
            >>"$spawn_log" 2>&1 || fail "powershell не смог запустить: $exe $* (см. $spawn_log)"
        pid="$(tr -cd '0-9' <"$pidf" 2>/dev/null || true)"
        case "$pid" in
            '' | *[!0-9]*) fail "PID не записан для: $exe $* (см. $spawn_log)" ;;
        esac
    else
        PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 nohup "$exe" "$@" >"$out" 2>"$err" &
        pid=$!
    fi
    printf '%s\n' "$pid" >"$pidf"
}

# Значение KEY из файла вида KEY=value (первое вхождение, без комментариев).
# Всегда завершается с кодом 0 — вызывается через $() под set -e.
file_value() {
    local file="$1" key="$2"
    [ -f "$file" ] || return 0
    sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$file" 2>/dev/null |
        head -n 1 | tr -d '\r' | sed 's/[[:space:]]*$//' || true
}

# Значение KEY из .env репозитория (env-переменные имеют приоритет сами по себе).
env_file_value() {
    file_value "$ROOT/.env" "$1"
}

# Хост-порт контейнера: docker port <container> <spec> -> 5435 | пусто.
# Контейнер может не существовать — это не ошибка (pipefail + set -e).
docker_port() {
    { docker port "$1" "$2" 2>/dev/null || true; } |
        head -n 1 | sed -n 's/.*:\([0-9]\{1,\}\)$/\1/p'
}

# --- 0. Lock от параллельного запуска ----------------------------------------
# Два одновременных start дают два uvicorn и гонку за pid-файлы. Лок снимается
# через trap; после жёсткого убийства процесса несуществующий pid чистится сам.
LOCK_FILE="$LOGS/start.sh.lock"
mkdir -p "$LOGS"
if [ -f "$LOCK_FILE" ]; then
    lock_pid="$(tr -cd '0-9' <"$LOCK_FILE" 2>/dev/null || true)"
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
        fail "start уже выполняется (pid $lock_pid) — дождитесь завершения"
    fi
    rm -f "$LOCK_FILE"
fi
printf '%s\n' "$$" >"$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# --- 1. Повторный запуск? ----------------------------------------------------
step "Проверка портов ($API_PORT API / $UI_PORT UI)"
if port_busy "$API_PORT"; then
    if port_is_docker "$API_PORT"; then
        fail "Порт $API_PORT занят контейнером Docker — похоже, стек уже поднят. Остановите: scripts/stop.sh"
    fi
    fail "Порт $API_PORT уже занят — агент, похоже, уже запущен. Остановите: scripts/stop.sh"
fi
if port_busy "$UI_PORT"; then
    if port_is_docker "$UI_PORT"; then
        fail "Порт $UI_PORT занят контейнером Docker — похоже, стек уже поднят. Остановите: scripts/stop.sh"
    fi
    fail "Порт $UI_PORT уже занят — UI, похоже, уже запущен. Остановите: scripts/stop.sh"
fi
done_msg "порты свободны"

# --- 2. Зависимости ----------------------------------------------------------
# В режиме --stack всё крутится в контейнерах: uv sync и .venv не нужны.
if [ "$STACK" = 1 ]; then
    step "Режим --stack: uv sync / локальный venv пропущены"
else
    if [ "$SKIP_SYNC" = 1 ]; then
        step "uv sync пропущен (--skip-sync)"
    else
        step "uv sync"
        uv sync || fail "uv sync завершился с кодом $?"
        done_msg "зависимости установлены"
    fi

    # Python из venv: модули запускаем напрямую (`python -m ...`), минуя
    # console-script .exe-лаунчеры — на Windows при старте через Start-Process
    # они не наследуют stdout/stderr, и логи в logs/*.log остаются пустыми.
    if [ "$IS_WINDOWS" = 1 ]; then
        PY_EXE="$ROOT/.venv/Scripts/python.exe"
    else
        PY_EXE="$ROOT/.venv/bin/python"
    fi
    [ -f "$PY_EXE" ] || fail ".venv не найден: $PY_EXE — запустите без --skip-sync (uv sync)"
fi

# --- 3. Docker daemon (+ автозапуск) ------------------------------------------
step "Docker daemon"
if ! docker info >/dev/null 2>&1; then
    if [ "$NO_DOCKER_START" = 1 ]; then
        fail "Docker недоступен (--no-docker-start) — запустите Docker daemon и повторите запуск"
    fi
    step "Docker daemon не запущен — автозапуск (до 120s, --no-docker-start отключает)"
    started=0
    if [ "$IS_WINDOWS" = 1 ]; then
        dd_exe="/c/Program Files/Docker/Docker/Docker Desktop.exe"
        if [ -f "$dd_exe" ]; then
            powershell -NoProfile -Command "Start-Process -FilePath '$(cygpath -w "$dd_exe")' -WindowStyle Hidden" \
                || fail "не удалось запустить Docker Desktop ($dd_exe)"
            started=1
        fi
    elif [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
        if [ -d "/Applications/Docker.app" ]; then
            open -a Docker || fail "не удалось запустить Docker.app"
            started=1
        fi
    else
        if command -v systemctl >/dev/null 2>&1; then
            if systemctl start docker 2>/dev/null || sudo -n systemctl start docker 2>/dev/null; then
                started=1
            fi
        fi
    fi
    if [ "$started" = 0 ]; then
        fail "Docker недоступен и автозапуск не сработал — запустите Docker вручную и повторите"
    fi
    i=0
    while [ "$i" -lt 40 ]; do
        if docker info >/dev/null 2>&1; then
            break
        fi
        sleep 3
        i=$((i + 1))
    done
    docker info >/dev/null 2>&1 || fail "Docker не поднялся за 120s — запустите его вручную"
    done_msg "Docker запущен"
fi
done_msg "Docker доступен"

# Хост-порты: env > .env > уже запущенный контейнер > дефолт compose.
# Произведённые значения экспортируются, чтобы `compose up` не пересоздавал
# существующие контейнеры, а миграции/API попали в тот же порт.
# Фолбэк: занятый порт, не являющийся нашим контейнером, при непрямом
# источнике (дефолт/runtime.env) → подбор свободного с +3; при явном
# источнике (env/.env) → fail-fast с именем владельца.
PG_EXPLICIT=0
PG_PORT=""
if [ -n "${POSTGRES_PORT:-}" ]; then
    PG_PORT="$POSTGRES_PORT"
    PG_EXPLICIT=1
else
    PG_PORT="$(env_file_value POSTGRES_PORT)"
    if [ -n "$PG_PORT" ]; then
        PG_EXPLICIT=1
    else
        detected="$(docker_port oryaagent-postgres-1 5432/tcp)"
        if [ -z "$detected" ]; then
            detected="$(file_value "$RUNTIME_FILE" POSTGRES_PORT)"
        fi
        if [ -n "$detected" ]; then
            PG_PORT="$detected"
            export POSTGRES_PORT="$PG_PORT"
            step "POSTGRES_PORT не задан — использую порт из запуска/контейнера: $PG_PORT"
        fi
    fi
fi
PG_PORT="${PG_PORT:-5432}"

REDIS_EXPLICIT=0
REDIS_PORT_VAL=""
if [ -n "${REDIS_PORT:-}" ]; then
    REDIS_PORT_VAL="$REDIS_PORT"
    REDIS_EXPLICIT=1
else
    REDIS_PORT_VAL="$(env_file_value REDIS_PORT)"
    if [ -n "$REDIS_PORT_VAL" ]; then
        REDIS_EXPLICIT=1
    else
        detected="$(docker_port oryaagent-redis-1 6379/tcp)"
        if [ -z "$detected" ]; then
            detected="$(file_value "$RUNTIME_FILE" REDIS_PORT)"
        fi
        if [ -n "$detected" ]; then
            REDIS_PORT_VAL="$detected"
            export REDIS_PORT="$REDIS_PORT_VAL"
            step "REDIS_PORT не задан — использую порт из запуска/контейнера: $REDIS_PORT_VAL"
        fi
    fi
fi
REDIS_PORT_VAL="${REDIS_PORT_VAL:-6379}"

# Занятость: наш контейнер уже на порту — это он; чужой слушатель — фолбэк
# (подбор свободного с +3). Явно заданный занятый порт обрабатывается
# заранее в check_port_conflict. Печатает результирующий порт.
# $1=порт $2=контейнер $3=спек
resolve_host_port() {
    local port="$1" container="$2" spec="$3"
    local ours owner_pid owner_name free
    ours="$(docker_port "$container" "$spec")"
    if [ -n "$ours" ] && [ "$ours" = "$port" ]; then
        echo "$port"
        return 0
    fi
    if ! port_busy "$port"; then
        echo "$port"
        return 0
    fi
    owner_pid="$(port_pids "$port" | head -n 1)"
    owner_name="$(proc_name "$owner_pid")"
    owner_name="${owner_name:-?}"
    free="$(free_port_from $((port + 3)))"
    if [ -z "$free" ]; then
        fail "порт $port занят (${owner_name}), свободных в диапазоне +30 не найдено"
    fi
    # stdout подстановки — это результат порта, сообщение уходит в stderr.
    step "порт $port занят (${owner_name}) — подбираю свободный: $free" >&2
    echo "$free"
}
# Явно заданный занятый порт = fail-fast с владельцем. Вызывается до
# resolve_host_port, поэтому fail печатается пользователю напрямую.
check_port_conflict() {
    local port="$1" key="$2" explicit="$3" container="$4" spec="$5"
    local ours owner_pid owner_name
    [ "$explicit" = 1 ] || return 0
    ours="$(docker_port "$container" "$spec")"
    if [ -n "$ours" ] && [ "$ours" = "$port" ]; then return 0; fi
    port_busy "$port" || return 0
    owner_pid="$(port_pids "$port" | head -n 1)"
    owner_name="$(proc_name "$owner_pid")"
    fail "$key=$port задан явно, но занят посторонним процессом ${owner_name:-?} (pid ${owner_pid:-?}) — освободите порт или задайте другой"
}
check_port_conflict "$PG_PORT" POSTGRES_PORT "$PG_EXPLICIT" oryaagent-postgres-1 5432/tcp
check_port_conflict "$REDIS_PORT_VAL" REDIS_PORT "$REDIS_EXPLICIT" oryaagent-redis-1 6379/tcp

NEW_PG_PORT="$(resolve_host_port "$PG_PORT" oryaagent-postgres-1 5432/tcp)"
if [ "$NEW_PG_PORT" != "$PG_PORT" ]; then
    PG_PORT="$NEW_PG_PORT"
fi
export POSTGRES_PORT="$PG_PORT"

NEW_REDIS_PORT="$(resolve_host_port "$REDIS_PORT_VAL" oryaagent-redis-1 6379/tcp)"
if [ "$NEW_REDIS_PORT" != "$REDIS_PORT_VAL" ]; then
    REDIS_PORT_VAL="$NEW_REDIS_PORT"
fi
export REDIS_PORT="$REDIS_PORT_VAL"

# Запоминаем выбранные порты ДО compose up: после `docker compose down`
# контейнеров нет, но следующий запуск должен поднять их на тех же
# хост-портах; при падении up выбор тоже сохраняется.
mkdir -p "$LOGS"
printf 'POSTGRES_PORT=%s\nREDIS_PORT=%s\n' "$PG_PORT" "$REDIS_PORT_VAL" >"$RUNTIME_FILE"

if [ "$STACK" = 1 ]; then
    # --- Режим --stack: полный контейнерный стек ----------------------------
    if [ "$SKIP_SYNC" = 1 ]; then
        step "--skip-sync не нужен в режиме --stack (uv sync и так пропущен)"
    fi
    if [ "$RELOAD" = 1 ]; then
        echo "!!  --reload не действует в режиме --stack (контейнеры)" >&2
    fi
    profiles=(--profile app)
    sibling="$(dirname "$ROOT")/OryaObservability"
    if [ -d "$sibling" ]; then
        profiles+=(--profile observability)
    else
        echo "!!  $sibling не найден — профиль observability пропущен (только app)" >&2
    fi
    # Порты API/UI уходят в compose (${API_PORT:-8000} / ${CHAINLIT_PORT:-8001}).
    export API_PORT CHAINLIT_PORT="$UI_PORT"
    step "docker compose ${profiles[*]} up -d --build"
    up_rc=0
    docker compose "${profiles[@]}" up -d --build || up_rc=$?
    if [ "$up_rc" -ne 0 ]; then
        docker compose "${profiles[@]}" logs --tail 60 >&2 || true
        fail "docker compose up завершился с кодом $up_rc (логи выше)"
    fi

    step "Ожидание Postgres (pg_isready)"
    pg_ready=0
    i=0
    while [ "$i" -lt 30 ]; do
        if docker compose exec -T postgres pg_isready -U orya -d orya_sessions >/dev/null 2>&1; then
            pg_ready=1
            break
        fi
        sleep 2
        i=$((i + 1))
    done
    [ "$pg_ready" = 1 ] || fail "Postgres не стал готов за 60s (docker compose logs postgres)"
    done_msg "Postgres готов"

    if ! wait_http "http://127.0.0.1:$API_PORT/health" 180 "API"; then
        docker compose "${profiles[@]}" logs --tail 60 api >&2 || true
        fail "API не ответил /health — подробности в логах выше"
    fi
    done_msg "API здоров: http://127.0.0.1:$API_PORT/health"
    if ! wait_http "http://127.0.0.1:$UI_PORT/" 120 "Chainlit"; then
        docker compose "${profiles[@]}" logs --tail 60 chainlit >&2 || true
        fail "UI не ответил — подробности в логах выше"
    fi
    done_msg "UI доступен: http://127.0.0.1:$UI_PORT/"
    case " ${profiles[*]} " in
        *" observability "*)
            # Langfuse v3 поднимается долго (миграции) — best-effort.
            wait_http "http://127.0.0.1:3000/api/public/health" 120 "Langfuse" 1 || true
            ;;
    esac

    echo
    echo "OryaAgent запущен (режим --stack, контейнеры)"
    echo "  API        : http://127.0.0.1:$API_PORT/health"
    echo "  UI         : http://127.0.0.1:$UI_PORT/"
    case " ${profiles[*]} " in
        *" observability "*)
            echo "  Langfuse   : http://127.0.0.1:3000/"
            echo "  Prometheus : http://127.0.0.1:9090/"
            echo "  Sampler    : http://127.0.0.1:4321/sampler/status"
            ;;
    esac
    echo "  Логи       : docker compose logs -f"
    echo "  Стоп       : scripts/stop.sh"
    exit 0
fi

step "docker compose up -d postgres redis"
docker compose up -d postgres redis || fail "docker compose up завершился с кодом $?"

step "Ожидание готовности Postgres (pg_isready)"
pg_ready=0
i=0
while [ "$i" -lt 30 ]; do
    if docker compose exec -T postgres pg_isready -U orya -d orya_sessions >/dev/null 2>&1; then
        pg_ready=1
        break
    fi
    sleep 2
    i=$((i + 1))
done
[ "$pg_ready" = 1 ] || fail "Postgres не стал готов за 60s (docker compose logs postgres)"
done_msg "Postgres готов"

# --- 4. URL'ы БД/Redis (env > .env > дефолт под фактический порт) ------------
if [ -z "${DATABASE_URL:-}" ] && [ -z "$(env_file_value DATABASE_URL)" ]; then
    export DATABASE_URL="postgresql://orya:orya_password@localhost:${PG_PORT}/orya_sessions"
    if [ "$PG_PORT" != "5432" ]; then
        step "DATABASE_URL -> localhost:$PG_PORT (порт существующего контейнера)"
    fi
elif [ "$PG_PORT" != "5432" ]; then
    configured="${DATABASE_URL:-$(env_file_value DATABASE_URL)}"
    db_port="$(printf '%s' "$configured" | sed -n 's|.*:\([0-9]\{1,\}\)/.*|\1|p')"
    if [ -n "$db_port" ] && [ "$db_port" != "$PG_PORT" ]; then
        echo "!!  DATABASE_URL указывает на порт $db_port, а контейнер БД на $PG_PORT — миграции/API могут не достучаться" >&2
    fi
fi
if [ -z "${REDIS_URL:-}" ] && [ -z "$(env_file_value REDIS_URL)" ]; then
    export REDIS_URL="redis://localhost:${REDIS_PORT_VAL}"
    if [ "$REDIS_PORT_VAL" != "6379" ]; then
        step "REDIS_URL -> localhost:$REDIS_PORT_VAL"
    fi
fi

# --- 5. Миграции -------------------------------------------------------------
step "Миграции БД (python -m app.db.migrate)"
uv run python -m app.db.migrate || fail "Миграции завершились с кодом $?"
done_msg "схема актуальна"

# --- 6. API (uvicorn) --------------------------------------------------------
step "Запуск API (uvicorn, порт $API_PORT)"
mkdir -p "$LOGS"
rm -f "$API_PID_FILE" "$UI_PID_FILE" "$API_LOG" "$API_ERR_LOG" "$UI_LOG" "$UI_ERR_LOG" \
    "$LOGS/api.spawn.log" "$LOGS/ui.spawn.log"

uvicorn_args=(-m uvicorn app.main:app --port "$API_PORT")
if [ "$RELOAD" = 1 ]; then
    uvicorn_args+=(--reload)
fi
spawn_bg "$API_LOG" "$API_ERR_LOG" "$API_PID_FILE" "$PY_EXE" "${uvicorn_args[@]}"
done_msg "API pid=$(cat "$API_PID_FILE") -> $API_LOG"

if ! wait_http "http://127.0.0.1:$API_PORT/health" 60 "API /health"; then
    show_log_tail "$API_ERR_LOG"
    show_log_tail "$API_LOG"
    fail "API не поднялся — подробности в логах выше"
fi
done_msg "API здоров: http://127.0.0.1:$API_PORT/health"

# --- 7. UI (Chainlit) ---------------------------------------------------------
# UI ходит в API по ORYA_API_URL — указываем на только что поднятый API.
api_url="http://127.0.0.1:$API_PORT"
if [ -n "${ORYA_API_URL:-}" ] && [ "$ORYA_API_URL" != "$api_url" ]; then
    echo "!!  ORYA_API_URL=$ORYA_API_URL не совпадает с портом API $API_PORT — UI может не достучаться" >&2
else
    export ORYA_API_URL="$api_url"
fi

step "Запуск UI (Chainlit, порт $UI_PORT)"
spawn_bg "$UI_LOG" "$UI_ERR_LOG" "$UI_PID_FILE" \
    "$PY_EXE" -m chainlit run app/ui/chainlit_app.py --port "$UI_PORT"
done_msg "UI pid=$(cat "$UI_PID_FILE") -> $UI_LOG"

if ! wait_http "http://127.0.0.1:$UI_PORT/" 60 "Chainlit"; then
    show_log_tail "$UI_ERR_LOG"
    show_log_tail "$UI_LOG"
    fail "UI не поднялся — подробности в логах выше; остановка: scripts/stop.sh"
fi
done_msg "UI доступен: http://127.0.0.1:$UI_PORT/"

# --- Итог --------------------------------------------------------------------
echo
echo "OryaAgent запущен"
echo "  API : http://127.0.0.1:$API_PORT  (health: /health)"
echo "  UI  : http://127.0.0.1:$UI_PORT/"
echo "  Логи: $LOGS"
echo "  Стоп: scripts/stop.sh"
