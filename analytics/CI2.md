# CI2 — Аудит CI/CD репозитория `Reider85/OryaAgent`

> Источник: `https://github.com/Reider85/OryaAgent` (ветка `main`, клон от 2026-11-14).
> Файл сформирован как набор готовых промптов для исполнителя (человека или AI-агента):
> каждый найденный баг снабжён самодостаточным промптом, который можно скопировать и применить.

---

## 0. Контекст проекта

OryaAgent — Python 3.11+ агент (FastAPI + LangGraph + Chainlit). Сборка: `uv` + `hatchling`. Деплой:
`docker compose v2` с профилями `app` / `observability`. Покрытие тестов: `tests/unit`, `tests/e2e`,
`tests/smoke`, `tests/integration`, `tests/performance`. Версия в `pyproject.toml`: `7.0.0`.

CI/CD-инвентарь (всё, что найдено в репо):

| Файл / директория | Назначение |
|---|---|
| `.github/workflows/ci.yml` | Lint → test-matrix (3.11–3.14) → integration (pg+redis) → pip-audit → build dist |
| `.github/workflows/release.yml` | Пререлиз на push в main + релиз на тег `v*.*.*` |
| `.github/workflows/release-drafter.yml` | Release Drafter по PR/labels |
| `.github/workflows/nightly.yml` | Ночной nightly-релиз (`@main`-pin) |
| `.github/workflows/codeql.yml` | CodeQL `security-and-quality` по Python |
| `.github/workflows/labels.yml` | Синхронизация `.github/labels.yml` |
| `.github/dependabot.yml` | pip + github-actions + docker (weekly/monthly) |
| `.github/release-drafter.yml` | Шаблон ченджлога и резолвер версий |
| `.github/labels.yml` | 17 лейблов |
| `.github/PULL_REQUEST_TEMPLATE.md` | Чек-лист PR |
| `.github/ISSUE_TEMPLATE/*.yml` | bug / feature / config |
| `CODEOWNERS` | Владелец + критичные зоны |
| `Makefile` | dev / test / lint / db / stack-up |
| `deploy/Dockerfile` | uv-многостадийный образ, Python 3.12, ripgrep |
| `docker-compose.yml` | postgres + redis + app + observability |

Все workflow-YAML парсятся корректно. **`docker-compose.yml` не парсится** — критическая ошибка (см. B-01).

---

## 1. Сводка по корректности

| ID | Серьёзность | Файл | Суть |
|---|---|---|---|
| **B-01** | 🔴 CRITICAL | `docker-compose.yml` | YAML не парсится: сервисы `api`, `oriahs-mcp` имеют 3-space отступ вместо 2, у `chainlit` смешаны 4/5-space отступы внутри блока |
| **B-02** | 🔴 CRITICAL | `tests/unit/test_docker_compose.py` | Все тесты падают на импорте `yaml.safe_load(COMPOSE_PATH)` из-за B-01; CI красный |
| **B-03** | 🟠 HIGH | `.github/workflows/release.yml:47` | Сломанный compare-URL `…/compare/...${{ github.event.before }}` (буквальный `...`, нет from-рефа, нет обработки `0000…` SHA) |
| **B-04** | 🟠 HIGH | `.github/workflows/release.yml` (push → main) | Пререлиз создаётся на **каждый** push в main без `paths-ignore`; десятки pre-release-тегов в неделю |
| **B-05** | 🟠 HIGH | `.github/workflows/nightly.yml:30` | `pyTooling/Actions/releaser@main` — пин к ветке `@main` (не immutable, риск供应链) |
| **B-06** | 🟠 HIGH | `.github/workflows/release-drafter.yml:6` | `pull_request_target` без `workflow_dispatch`-проверки и без `permissions: {}` для external PR — потенциальная escalation surface |
| **B-07** | 🟠 HIGH | `.github/workflows/ci.yml:54` | `pytest … -x` останавливает матрицу на первом fail; остальные тесты скрыты |
| **B-08** | 🟠 HIGH | `ci.yml` (build job) | Build dist собирает wheel/sdist, но **Docker-образ не собирается и не пушится в ghcr.io**, который обещан в `release-drafter.yml:25` (`docker pull ghcr.io/...`) |
| **B-09** | 🟡 MEDIUM | `.github/workflows/nightly.yml:40` | `$(date -u)` в YAML `body:` — literal, не интерполируется в shell (нет `run:`) |
| **B-10** | 🟡 MEDIUM | `ci.yml` (integration) | Интеграция только на Python 3.12 (нет матрицы), в то время как `requires-python>=3.11` и матрица test-matrix 4 версии |
| **B-11** | 🟡 MEDIUM | `ci.yml:122` | `pip-audit --strict` с `continue-on-error: true` — уязвимости никогда не блокируют релиз; нет issue-auto-create |
| **B-12** | 🟡 MEDIUM | `ci.yml` | Нет шага type-check (`mypy`/`pyright`), хотя проект активно использует typing (Pydantic v2, generics) |
| **B-13** | 🟡 MEDIUM | `ci.yml:54` | `--cov-report=xml` пишется во все 4矩阵-раннерах, но Codecov грузит только с 3.12; остальные 3 артефакта теряются |
| **B-14** | 🟡 MEDIUM | `release.yml:32` | Версия тега парсится `grep '^version'` — хрупко; при наличии секции `[tool.*]` с `version = …` будет дубликат |
| **B-15** | 🟡 MEDIUM | `ci.yml` (build) | `actions/upload-artifact@v4` без `retention-days` и без `if: github.event_name == 'push'` — артефакты копятся на PR |
| **B-16** | 🟢 LOW | `ci.yml` lint | Нет `--frozen` для `ruff format --check` при matrix-тесте; `ruff` cache не включён |
| **B-17** | 🟢 LOW | `.github/workflows/codeql.yml` | `paths-ignore` применён к push, но **не к pull_request** → CodeQL гоняется на docs-PR |
| **B-18** | 🟢 LOW | `Makefile` | `make stack-up` не передаёт `--profile`, `make stack-down` передаёт `--profile app --profile observability` — асимметрия |
| **B-19** | 🟢 LOW | `release.yml:82` | Literal placeholder `(заполни вручную…)` попадает в GitHub Release body как есть |
| **B-20** | 🟢 LOW | `.github/dependabot.yml` | Docker-экосистема указана на `/deploy`, но `docker-compose.yml` (там же образы `postgres:16`, `redis:7`, `clickhouse:26.9`, `prom/prometheus:v3.4.2`) не покрывается dependabot-обновлениями базовых образов (только `deploy/Dockerfile`) |
| **B-21** | 🟢 LOW | `ci.yml` | Нет `timeout-minutes` на job-уровне; зависший integration-тест крутится до дефолтных 6 часов |
| **B-22** | 🟢 LOW | `release-drafter.yml:17` | Шаблон `release-drafter.yml` предлагает `docker pull ghcr.io/reider85/oryaagent:$RESOLVED_VERSION`, но образа там нет (см. B-08) → инструкция врелизе вводит в заблуждение |

---

## 2. Промпты на исправление (готовы к копированию)

> Каждый промпт самодостаточен: исполнитель применяет правки в репо `OryaAgent` и присылает PR
> с названием, указанным в начале блока. Все правки должны сохранять существующий стиль
> (2-space YAML-отступ, double-quote в `ruff format`).

### 🔴 B-01 — Починить YAML-отступы в `docker-compose.yml`

**PR title:** `fix(compose): repair YAML indentation of api/oriahs-mcp/chainlit services`

```
В файле docker-compose.yml репозитория OryaAgent нарушена YAML-индентация, поэтому
`docker compose config -q` и `yaml.safe_load(open('docker-compose.yml'))` падают с
`yaml.parser.ParserError: expected <block end>, but found '<block mapping start>'`.

Конкретные проблемы:
1. Сервис `api:` (строка ~100) имеет 3-пробельный отступ вместо 2. Весь блок
   `profiles / build / image / restart / command / env_file / environment / ports /
   volumes / working_dir / depends_on / healthcheck` сдвинут на +1 пробел.
2. Сервис `oriahs-mcp:` (строка ~173) — то же самое: 3 пробела вместо 2, весь блок
   сдвинут на +1.
3. Внутри сервиса `chainlit:` ключи `depends_on:` и `healthcheck:` (строки ~161, ~166)
   имеют 5 пробелов, тогда как их соседи (`profiles`, `image`, `command`, `env_file`,
   `environment`, `ports`) — 4 пробела. Это смешение siblings внутри одного mapping.

Что сделать:
- Привести ВСЕ ключи сервисов к 2-space отступу (как у `postgres`, `redis`, `db-init`,
  `clickhouse`, `minio`, `langfuse`, `langfuse-worker`, `sampler-proxy`, `prometheus`,
  `clickhouse-obs-init`).
- Внутри каждого сервиса — 4-space для прямых детей, 6-space для внуков, 8-space
  для правнуков (как в `chainlit`).
- После правки запустить:
    python -c "import yaml; yaml.safe_load(open('docker-compose.yml')); print('OK')"
    docker compose config -q
- Убедиться, что `pytest tests/unit/test_docker_compose.py -q` проходит полностью
  (включая `test_docker_compose_config_validates`).
- Не менять ни одного значения, комментария или порядка ключей — только пробелы.

Контрольный чек-лист (после правки должен сработать каждый):
  yaml.safe_load(open('docker-compose.yml'))['services']['api']['image'] == 'orya-agent:local'
  yaml.safe_load(open('docker-compose.yml'))['services']['chainlit']['depends_on']['api']['condition'] == 'service_healthy'
  yaml.safe_load(open('docker-compose.yml'))['services']['oriahs-mcp']['profiles'] == ['app']
```

---

### 🔴 B-02 — Восстановить тесты `test_docker_compose.py`

**PR title:** `test(compose): unbreak test_docker_compose.py blocked by B-01`

```
После применения фикса B-01 файл tests/unit/test_docker_compose.py снова должен
загружаться yaml.safe_load. Дополнительно:

1. Запустить `uv run pytest tests/unit/test_docker_compose.py -v` и убедиться, что
   все 18 тестов проходят (включая параметризованный test_docker_compose_config_validates
   для profiles () и ("app",)). Если docker недоступен на CI-раннере, этот тест должен
   корректно skip-аться через pytest.skip — что уже сделано.
2. Добавить в test_docker_compose.py новый тест test_compose_yaml_is_parseable,
   который вызывает `yaml.safe_load(COMPOSE_PATH.read_text())` и проверяет, что
   ключ `services` существует и содержит минимум 13 сервисов. Это regression-test,
   который словит возврат B-01 в будущем.
3. В .github/workflows/ci.yml добавить шаг в job lint или отдельный job compose-lint:
       - name: Validate docker-compose.yml parses
         run: |
           uv run python -c "import yaml,sys; \
             data=yaml.safe_load(open('docker-compose.yml')); \
             assert 'services' in data and len(data['services'])>=13, 'compose broken'; \
             print('OK', list(data['services']))"
   Это запретит мердж broken-YAML PR-ов в будущем.
```

---

### 🟠 B-03 — Починить compare-URL в `release.yml`

**PR title:** `fix(release): correct compare URL in prerelease body`

```
В .github/workflows/release.yml на строке ~47 тело пререлиза содержит:

    Full changelog: https://github.com/${{ github.repository }}/compare/...${{ github.event.before }}

Эта ссылка нерабочая:
- Между `/compare/` и `${{ github.event.before }}` стоит literal `...`, но GitHub
  expects формат `/compare/<from>...<to>` или `/compare/<from>..<to>`. Здесь `<from>`
  отсутствует — ссылка ведёт на 404.
- На первый push в ветку `github.event.before` равен `0000000000000000000000000000000000000000`,
  что тоже нерабочая ссылка.

Что сделать:
1. Заменить строку на корректный формат:
       Full changelog: https://github.com/${{ github.repository }}/compare/${{ github.event.before }}...${{ github.sha }}
2. Добавить guard для initial-push (40 нулей). Использовать step с output:
       - name: Compute compare URL
         id: cmp
         run: |
           BEFORE="${{ github.event.before }}"
           if [ "${#BEFORE}" -eq 40 ] && [ "${BEFORE//0/}" = "" ]; then
             URL="https://github.com/${{ github.repository }}/commits/${{ github.sha }}"
           else
             URL="https://github.com/${{ github.repository }}/compare/${BEFORE}...${{ github.sha }}"
           fi
           echo "url=$URL" >> $GITHUB_OUTPUT
   и в body подставить `${{ steps.cmp.outputs.url }}`.
3. Проверить вручную на тестовом push в ветку main: открылся ли Release, кликабельна ли
   ссылка Full changelog.
```

---

### 🟠 B-04 — Не спамить pre-release на каждый push в `main`

**PR title:** `fix(release): gate prerelease-on-push by paths-ignore + dedup`

```
Сейчас .github/workflows/release.yml запускает job `prerelease-on-push` на КАЖДЫЙ
push в main. Это создаёт десятки pre-release-тегов вида
`v7.0.0-dev.${GITHUB_RUN_NUMBER}+${SHORT_SHA}` в неделю и засоряет страницу релизов.

Что сделать (минимально-инвазивно):

1. Добавить paths-ignore в триггер push (как в ci.yml):
     on:
       push:
         branches: [main]
         paths-ignore:
           - "**.md"
           - "docs/**"
           - "LICENSE"
           - ".github/**"        # сами workflows не должны триггерить релиз
           - "tests/**"          # тесты — не релиз
           - "scripts/**"

2. Идеально — убрать триггер push из release.yml совсем и оставить только `tags: ["v*.*.*"]`
   + `workflow_dispatch`. Пререлиз тогда делается вручную (workflow_dispatch) или из nightly.
   Это меняет семантику, согласовать с командой.

3. Если push-пререлиз важен для dogfooding — добавить dedup: в начале job проверить,
   есть ли уже release с этим SHA, через gh CLI:
       - name: Skip if release for this SHA exists
         id: dedup
         run: |
           if gh release view "v${VERSION}-dev.${GITHUB_RUN_NUMBER}+${SHORT_SHA}" \
              --repo "${{ github.repository }}" >/dev/null 2>&1; then
             echo "exists=true" >> $GITHUB_OUTPUT
           else
             echo "exists=false" >> $GITHUB_OUTPUT
           fi
   и обернуть шаг `Create prerelease` в `if: steps.dedup.outputs.exists != 'true'`.
   Но `GITHUB_RUN_NUMBER` монотонно растёт — dedup через SHA более корректен:
       SHA_TAG=$(gh release list --repo "${{ github.repository }}" --json tagName, \
                 --jq ".[] | select(.tagName|endswith(\"+${SHORT_SHA}\")) | .tagName" | head -1)
       if [ -n "$SHA_TAG" ]; then echo "exists=true" >> $GITHUB_OUTPUT; fi

4. Поставить `make_latest: "false"` (уже есть) — оставить.

5. В README badges использовать `?include_prereleases=false` для основного `github/v/release`
   или вынести pre-release в отдельный badge, чтобы визуально отделить.
```

---

### 🟠 B-05 — Заменить `@main` pin в `nightly.yml` на SHA

**PR title:** `ci(nightly): pin pyTooling/Actions/releaser to immutable SHA`

```
.github/workflows/nightly.yml строка ~30:
    uses: pyTooling/Actions/releaser@main

`@main` — пин к mutable ветке: любой коммит в upstream (включая скомпрометированный)
молча изменит поведение workflow. Это violates GitHub security best practices и
провалит любой serious security review.

Что сделать:
1. Зайти на https://github.com/pyTooling/Actions/releases, найти последний stable
   release тег releaser-action (например `v0.4.x`).
2. Скопировать commit SHA, на который указывает тег (кнопка "Copy full SHA" на странице тега).
3. Заменить строку на:
       uses: pyTooling/Actions/releaser@<40-char-SHA>
   с комментарием:
       # pyTooling/Actions releaser v0.4.x — pinned by SHA (B-05)
4. Добавить в .github/dependabot.yml группу для пинов (уже есть github-actions ecosystem —
   Dependabot сам предложит bump SHA→новый тег).
5. Альтернатива: если action избыточен для одного шага "create-or-update tag+release",
   заменить на `softprops/action-gh-release@v2` с `allow_update: true` — он уже
   используется в release.yml, что убирает лишнюю зависимость.
6. Запустить nightly вручную (`gh workflow run nightly.yml`) и проверить, что релиз создался.
```

---

### 🟠 B-06 — Защитить `release-drafter.yml` от `pull_request_target` эскалации

**PR title:** `ci(release-drafter): drop pull_request_target in favor of pull_request`

```
.github/workflows/release-drafter.yml использует триггер `pull_request_target`,
который запускается с правами `secrets.GITHUB_TOKEN` репозитория ДЛЯ ЛЮБОГО PR,
включая форки. release-drafter@v6 внутри проверяет права, но сам триггер —
известный анти-паттерн для public репо.

Что сделать (вариант A, минимальный):
1. Заменить `pull_request_target` на `pull_request` (workflow запустится без секретов
   от внешних форков — безопасно):
     on:
       push:
         branches: [main]
       pull_request:
         types: [opened, reopened, labeled, unlabeled, synchronize]
   В permissions оставить:
     contents: read
     pull-requests: write
2. release-drafter@v6 при `pull_request` корректно работает для PR из форков
   (draft updating ограничен, но базовый ченджлог генерируется).

Вариант B (если нужен именно pull_request_target для labelled-PR из форков):
1. Добавить явный шаг проверки actor перед вызовом release-drafter:
       - name: Block fork PRs from drafter
         if: github.event_name == 'pull_request_target' && github.event.pull_request.head.repo.fork
         run: exit 1
2. Зафиксировать SHA release-drafter:
       uses: release-drafter/release-drafter@<SHA-from-v6.0.0>
3. Минимизировать permissions:
       permissions:
         contents: read
         pull-requests: write
   (уже так — оставить).

Выбрать вариант A, если нет hard-требования обновлять draft по labels из форков.
```

---

### 🟠 B-07 — Убрать `-x` из pytest в `ci.yml`

**PR title:** `ci(test): drop -x so matrix surfaces all failures`

```
.github/workflows/ci.yml строка ~54:
    run: uv run pytest tests/unit tests/e2e tests/smoke --cov=app --cov-report=xml --cov-report=term-missing -x

Флаг `-x` (stop on first failure) прячет остальные тесты за одним упавшим. Для CI
матрицы 4×Python это означает: упал один import-тест — увидели только его, остальные
30 тестов даже не запустились. Разработчик итеративно чинит по одному багу за прогон.

Что сделать:
1. Убрать `-x`. Заменить на `--maxfail=10` (если нужно ограничение) или просто убрать.
2. Добавить `--continue-on-collection-errors` чтобы ошибка импорта в одном модуле
   не блокировала остальные:
       uv run pytest tests/unit tests/e2e tests/smoke \
         --cov=app --cov-report=xml --cov-report=term-missing \
         --continue-on-collection-errors --maxfail=20
3. То же самое применить к integration-тесту (строка ~107):
       uv run pytest tests/integration --tb=short -k "not live" \
         --continue-on-collection-errors
   (здесь `-x` неявно нет, но `--tb=short` уже стоит — добавить `--maxfail=20`).
4. Убедиться, что Codecov всё ещё получает coverage.xml (он грузится по артефакту,
   не зависит от `-x`).
5. В README dev-документации указать, что локально `make test` всё ещё может
   использовать `-x` (разработчику удобно), но CI — нет.
```

---

### 🟠 B-08 — Собирать и пушить Docker-образ в GHCR

**PR title:** `ci(release): build & push image to ghcr.io on tag`

```
deploy/Dockerfile существует, docker-compose.yml использует `image: orya-agent:local`,
release-drafter.yml:25 обещает `docker pull ghcr.io/reider85/oryaagent:$RESOLVED_VERSION`,
но НИ ОДНА workflow не собирает образ и не пушит его в GHCR. Релизные инструкции
в релизе сломаны.

Что сделать:

1. Добавить новый job `docker` в .github/workflows/release.yml (только в `release-on-tag`):
     docker:
       name: Build & push image
       needs: []   # параллельно release-on-tag
       if: startsWith(github.ref, 'refs/tags/v')
       runs-on: ubuntu-latest
       permissions:
         contents: read
         packages: write
       steps:
         - uses: actions/checkout@v4
         - uses: docker/setup-buildx-action@v3
         - uses: docker/login-action@v3
           with:
             registry: ghcr.io
             username: ${{ github.actor }}
             password: ${{ secrets.GITHUB_TOKEN }}
         - name: Extract metadata
           id: meta
           uses: docker/metadata-action@v5
           with:
             images: ghcr.io/${{ github.repository }}
             tags: |
               type=ref,event=tag
               type=semver,pattern={{version}}
               type=semver,pattern={{major}}.{{minor}}
               type=sha,prefix=sha-,format=short
         - uses: docker/build-push-action@v6
           with:
             context: .
             file: deploy/Dockerfile
             push: true
             tags: ${{ steps.meta.outputs.tags }}
             labels: ${{ steps.meta.outputs.labels }}
             cache-from: type=gha
             cache-to: type=gha,mode=max

2. Для пререлиза (push в main) добавить аналогичный job с тегом `sha-<short>` и `main`,
   помеченный как `prerelease` через docker/metadata-action.

3. В docker-compose.yml заменить `image: orya-agent:local` на параметризованное:
       image: ${ORYA_IMAGE:-ghcr.io/reider85/orya-agent:latest}
   и добавить `ORYA_IMAGE` в .env.example. Локальный dev оставляет `orya-agent:local`
   через build-override (build section уже есть).

4. В .github/dependabot.yml docker-экосистему оставить на `/` (а не `/deploy`), чтобы
   покрывался и Dockerfile, и docker-compose.yml image references:
       - package-ecosystem: "docker"
         directory: "/"
         schedule:
           interval: "weekly"

5. Добавить в README секцию "Pull pre-built image":
       docker pull ghcr.io/reider85/orya-agent:latest
       docker run --rm -p 8000:8000 ghcr.io/reider85/orya-agent:latest
```

---

### 🟡 B-09 — Убрать literal `$(date -u)` из `nightly.yml`

**PR title:** `fix(nightly): interpolate date via shell step, not YAML body`

```
.github/workflows/nightly.yml строка ~40:
    body: |
      Nightly build from main @ ${{ steps.ver.outputs.tag }}
      Версия pyproject: ${{ steps.ver.outputs.version }}
      Дата: $(date -u)

`$(date -u)` внутри YAML-поля `body:` — literal строка, она попадёт в релиз как текст
"Дата: $(date -u)". Shell-интерполяция работает только внутри `run:` шагов.

Что сделать:
1. В шаг `Resolve tag` (id: ver) добавить вычисление даты:
       DATE_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
       echo "date=$DATE_ISO" >> $GITHUB_OUTPUT
2. В `body:` заменить `$(date -u)` на `${{ steps.ver.outputs.date }}`:
       body: |
         Nightly build from main @ ${{ steps.ver.outputs.tag }}
         Версия pyproject: ${{ steps.ver.outputs.version }}
         Дата: ${{ steps.ver.outputs.date }}
3. Проверить на workflow_dispatch: открыть релиз, убедиться, что дата в ISO.
```

---

### 🟡 B-10 — Матрица для integration-теста

**PR title:** `ci(integration): matrix-test across Python 3.11/3.12/3.13`

```
.github/workflows/ci.yml integration-job использует фиксированный Python 3.12,
хотя pyproject.toml требует >=3.11, а test-matrix тестирует 3.11–3.14.
Интеграционные тесты (postgres+redis) не проверяются на 3.11/3.13.

Что сделать:
1. Обернуть integration в matrix:
     strategy:
       fail-fast: false
       matrix:
         python-version: ["3.11", "3.12", "3.13"]
   (3.14 пропускаем — asyncpg/psycopg могут не иметь wheels, добавить когда
   上游 выпустит.)
2. В steps заменить `python-version: "3.12"` на `${{ matrix.python-version }}`.
3. В setup-uv добавить `python-version: ${{ matrix.python-version }}` (как в test-matrix).
4. Добавить timeout-minutes: 15 на job.
5. Если matrix-валятся из-за asyncio API differences — оставить только 3.12
   с комментарием "# 3.11/3.13 добавлены когда asyncpg issues #412 закроется".
6. В Job-summary дать осмысленное name: Integration (Python ${{ matrix.python-version }}).
```

---

### 🟡 B-11 — `pip-audit` должен создавать issue и блокировать high CVE

**PR title:** `ci(audit): fail on high/critical CVEs and auto-file issue`

```
Сейчас pip-audit имеет continue-on-error: true — любые уязвимости, включая RCE,
молча игнорируются.

Что сделать:
1. Разделить audit на два прохода:
   a) Блокирующий: только high/critical (CVSS >= 7.0):
        - name: Audit (block on high/critical)
          run: |
            uv run pip-audit --strict --desc --output json > audit.json || true
            python scripts/audit_gate.py audit.json   # exit 1 если есть CVSS>=7
   b) Информативный: остальные:
        - name: Audit (report all)
          run: uv run pip-audit --strict --desc
          continue-on-error: true
2. Создать scripts/audit_gate.py (Python 3.11+):
       - читает audit.json (pip-audit --output json)
       - для каждой уязвимости проверяет поле `cve` → запрос к NVD API
         (https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=...)
         → парсит CVSS
       - exit 1, если хотя бы одна CVSS >= 7.0
       - print summary в stdout
3. Если audit-gate упал — создать GitHub Issue (action.yml):
       - name: File security issue
         if: failure()
         uses: JasonEtco/create-an-issue@v2
         env:
           GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
         with:
           filename: .github/ISSUE_TEMPLATE/audit_failure.md
           assignees: Reider85
           labels: security, dependencies
4. Создать .github/ISSUE_TEMPLATE/audit_failure.md с переменными:
       {{ env.AUDIT_SUMMARY }}, {{ env.AUDIT_JSON }}.
5. Не использовать NVD API без токена на public CI (rate limit 5 req/anonymous/IP/min).
   Запросить NVD API key (бесплатно) и положить в secrets.NVD_API_KEY.
```

---

### 🟡 B-12 — Добавить `mypy` в lint job

**PR title:** `ci(lint): add mypy type-check`

```
pyproject.toml активирует typing через Pydantic v2, generics, TYPE_CHECKING.
CI не запускает mypy.

Что сделать:
1. Добавить в pyproject.toml [tool.mypy]:
       python_version = "3.12"
       strict = true
       plugins = ["pydantic.mypy"]
       ignore_missing_imports = true   # временно, для langchain/chainlit
       warn_unused_ignores = true
       warn_redundant_casts = true
       disallow_untyped_defs = false   # включить после миграции
       exclude = ['tests/', 'alembic/versions/']
2. В .github/workflows/ci.yml job `lint` добавить шаг:
       - name: Type-check (mypy)
         run: uv run mypy app
   (поставить ПОСЛЕ ruff, чтобы mypy видел уже отформатированный код)
3. Добавить mypy в [project.optional-dependencies] dev = [..., "mypy>=1.10"].
4. Запустить локально `uv run mypy app` — наверняка будет много ошибок. Сделать
   baseline:
       uv run mypy app --lineprecision-report mypy_report/
   Создать .mypy_cache-ignored baseline через mypy --baseline (если доступно) или
   вручную: на первом этапе разрешить warnings через `# type: ignore[<code>]`,
   documented в commits. Цель — green mypy на app/ за 2 недели.
5. Добавить `make typecheck: uv run mypy app` в Makefile.
```

---

### 🟡 B-13 — Грузить coverage только один раз, без потерь

**PR title:** `ci(coverage): consolidate coverage upload`

```
ci.yml test-matrix: `--cov-report=xml` пишется во всех 4 раннерах (3.11/3.12/3.13/3.14),
но Codecov грузит только с 3.12. Артефакты с 3.11/3.13/3.14 теряются.

Что сделать (вариант A — минимальный):
1. Оставить --cov-report=xml во всех 4 раннерах.
2. Добавить `actions/upload-artifact@v4` в каждом:
       - name: Upload coverage XML
         uses: actions/upload-artifact@v4
         with:
           name: coverage-py${{ matrix.python-version }}
           path: coverage.xml
           retention-days: 7
3. Добавить отдельный job `coverage` после test-matrix:
       coverage:
         needs: [test-matrix]
         runs-on: ubuntu-latest
         steps:
           - uses: actions/download-artifact@v4
             with:
               pattern: coverage-py*
               merge-multiple: false
           - uses: codecov/codecov-action@v5
             with:
               token: ${{ secrets.CODECOV_TOKEN }}
               fail_ci_if_error: false
               files: coverage-py3.11/coverage.xml,coverage-py3.12/coverage.xml,...
   Или загрузить через codecov CLI с --flags=py3.11 и т.д.

Вариант B (если coverage от 3.11/3.13/3.14 не нужен):
  Сделать coverage только на 3.12 (как сейчас), но убрать --cov-report=xml из
  остальных, оставив --cov-report=term-missing. Уменьшает runtime.

Выбрать вариант A, если нужен cross-version coverage trend.
```

---

### 🟡 B-14 — Парсить версию через `tomllib`, а не grep

**PR title:** `fix(release): parse version via Python tomllib, not grep`

```
release.yml и nightly.yml парсят версию:
    VERSION=$(grep -m1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')

Это хрупко:
- Если в pyproject.toml появится секция [tool.some-tool] с полем `version = "1.2.3"`,
  grep -m1 возьмёт ПЕРВУЮ строку, начинающуюся с `version` — а это может быть
  tool-секция, а не [project].
- Если `[project] version` переехал в `version = { file = "VERSION" }` — сломается.

Что сделать:
1. В обоих workflow заменить grep на:
       VERSION=$(uv run python -c "import tomllib; \
                 print(tomllib.loads(open('pyproject.toml','rb').read().decode())\
                 ['project']['version'])")
   (uv уже установлен, не требует лишних deps; tomllib в stdlib с 3.11.)
2. Или ещё чище — добавить в Makefile цель `version`:
       version:
           @uv run python -c "import tomllib,sys; \
             print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
   и в workflow: `VERSION=$(make version)`.
3. Smoke-тест: убедиться, что `make version` == `7.0.0` локально.
```

---

### 🟡 B-15 — Не плодить артефакты на PR

**PR title:** `ci(build): gate artifact upload + retention-days`

```
ci.yml build job загружает dist/ через actions/upload-artifact@v4 без условий.
На каждый PR создаётся артефакт dist, который хранится 90 дней по умолчанию.

Что сделать:
1. Загружать артефакт только на push в main или на tag:
       - name: Upload dist artifact
         if: github.event_name == 'push' || startsWith(github.ref, 'refs/tags/v')
         uses: actions/upload-artifact@v4
         with:
           name: dist
           path: dist/
           retention-days: 14
           if-no-files-found: error
2. На PR — генерировать, но не загружать (или загружать с retention-days: 1).
3. Для release-on-tag — заливать артефакт прямо в Release через softprops/action-gh-release
   (уже сделано в release.yml).
4. Добавить `if-no-files-found: error` чтобы словить ситуацию, когда build ничего
   не произвёл.
```

---

### 🟢 B-16 — Включить ruff cache и зафиксировать `--frozen`

**PR title:** `ci(lint): enable ruff cache, drop redundant checks`

```
ci.yml lint:
- `uv sync --frozen` уже есть (good).
- `uv run ruff check .` и `uv run ruff format --check .` — каждый раз без cache.

Что сделать:
1. Включить ruff cache:
       - run: uv run ruff check . --cache-dir ~/.cache/ruff
         shell: bash
   ruff сам использует cache по умолчанию, но `--cache-dir` фиксирует место для
   display в Actions cache.
2. Закэшировать ~/.cache/ruff через actions/cache@v4:
       - uses: actions/cache@v4
         with:
           path: ~/.cache/ruff
           key: ruff-${{ runner.os }}-${{ hashFiles('uv.lock') }}
           restore-keys: ruff-${{ runner.os }}-
3. setup-uv уже кэширует venv через enable-cache: true — этого достаточно.
4. В Makefile добавить `make check: lint test` (уже частично есть).
```

---

### 🟢 B-17 — Применить `paths-ignore` к `pull_request` в CodeQL

**PR title:** `ci(codeql): skip docs-only PRs`

```
.github/workflows/codeql.yml:
  on:
    push:
      branches: [main]
      paths-ignore: ["**.md", "docs/**"]
    pull_request:
      branches: [main]    # ← нет paths-ignore

CodeQL будет гоняться на PR, который правит только README. Это лишние ~10 минут.

Что сделать:
1. Добавить paths-ignore в pull_request:
       pull_request:
         branches: [main]
         paths-ignore:
           - "**.md"
           - "docs/**"
           - "LICENSE"
2. Дополнительно можно игнорировать тесты (CodeQL будет сканировать их как prod-code):
       paths-ignore:
         - "tests/**"
   Но это зависит от threat model — тесты могут содержать vulnerable patterns,
   которые распространятся в prod через copy-paste. Оставить tests/ в сканировании.
3. Убедиться, что CodeQL всё ещё запускается на изменения в app/, deploy/, alembic/.
```

---

### 🟢 B-18 — Симметричные `stack-up` / `stack-down` в Makefile

**PR title:** `chore(make): align stack-up and stack-down profile flags`

```
Makefile:
  stack-up:
    docker compose up -d --build          # без --profile
  stack-down:
    docker compose --profile app --profile observability down

Если запускать make stack-up без COMPOSE_PROFILES env — поднимется только postgres/redis,
а make stack-down остановит всё. Это нарушает UX: пользователь ждёт app-стек, а получает
инфру.

Что сделать (выбрать одно):
A. stack-up с теми же профилями:
     stack-up:
       docker compose --profile app --profile observability up -d --build
B. stack-up с переменной:
     stack-up:
       docker compose --profile $${COMPOSE_PROFILES:-app,observability} up -d --build
   Но COMPOSE_PROFILES — env, не arg; нужен другой механизм.
C. Разделить:
     stack-infra:
       docker compose up -d postgres redis
     stack-app:
       docker compose --profile app up -d --build
     stack-obs:
       docker compose --profile observability up -d --build
     stack-up: stack-infra stack-app stack-obs
     stack-down:
       docker compose --profile app --profile observability down
   Это самый явный вариант — рекомендуется.

Дополнительно: в README указать, что `make stack-up` поднимает всё, `make stack-infra` —
только db/cache.
```

---

### 🟢 B-19 — Убрать placeholder из release body

**PR title:** `docs(release): drop placeholder text from tag-release body`

```
release.yml строка ~82:
    body: |
      ## OryaAgent ${{ github.ref_name }}
      ### Highlights
      (заполни вручную или доверь auto-generated notes ниже)

Этот literal "(заполни вручную…)" попадает в GitHub Release как видимый текст.

Что сделать:
1. Удалить строку `(заполни вручную или доверь auto-generated notes ниже)`.
2. Заменить на инструкцию для генерации:
       body: |
         ## OryaAgent ${{ github.ref_name }}

         ### Highlights

         <!-- Если есть breaking changes или важные migration notes —
              допиши сюда ДО merge тега. Иначе relied на auto-generated notes ниже. -->

         ### Installation
         ...
3. Альтернатива: убрать `body:` совсем и положиться на `generate_release_notes: true`,
   который сам сгенерирует markdown из PR titles/labels.
```

---

### 🟢 B-20 — Dependabot покрывает `docker-compose.yml` образы

**PR title:** `ci(dependabot): watch docker-compose image references`

```
.github/dependabot.yml:
  - package-ecosystem: "docker"
    directory: "/deploy"
    schedule: { interval: "monthly" }

Это покрывает только `deploy/Dockerfile` (FROM ghcr.io/astral-sh/uv:python3.12-...).
Но в docker-compose.yml есть:
  postgres:16, redis:7, clickhouse/clickhouse-server:26.9,
  prom/prometheus:v3.4.2, langfuse/langfuse:3, langfuse/langfuse-worker:3,
  quay.io/minio/minio:latest

Ни один не обновляется dependabot. minio:latest — особенно опасно.

Что сделать:
1. Заменить в docker-compose.yml `quay.io/minio/minio:latest` на конкретный тег
   (например `quay.io/minio/minio:RELEASE.2024-10-13T13-34-11Z`).
   То же для `langfuse/langfuse:3` → `langfuse/langfuse:3.42.0` (точный minor).
2. В dependabot.yml добавить ещё одну запись для корня compose:
     - package-ecosystem: "docker-compose"
       directory: "/"
       schedule: { interval: "weekly" }
       open-pull-requests-limit: 5
       labels: ["dependencies", "docker"]
   `docker-compose` — отдельная экосистема в Dependabot (парсит image: поля).
3. Запустить dependabot locally: `dependabot script` или триггернуть через PR
   в .github/dependabot.yml — Dependabot создаст PR-ы на новые теги.
4. Pin все `:latest` и `:3` к конкретным версиям в docker-compose.yml.
```

---

### 🟢 B-21 — `timeout-minutes` на каждый CI job

**PR title:** `ci: add timeout-minutes to all jobs`

```
ci.yml: ни один job не имеет timeout-minutes. По умолчанию GitHub убивает через
6 часов (360 minutes). Зависший integration-тест (postgres connection leak,
async deadlock) будет крутиться 6 часов, тратя actions-minutes.

Что сделать:
1. На каждый job в ci.yml добавить:
       lint:         timeout-minutes: 5
       test-matrix:  timeout-minutes: 20
       integration:  timeout-minutes: 15
       audit:        timeout-minutes: 10
       build:        timeout-minutes: 10
2. В codeql.yml уже есть timeout-minutes: 30 на analyze — OK.
3. В release.yml и nightly.yml добавить:
       release-on-tag:    timeout-minutes: 15
       prerelease-on-push: timeout-minutes: 10
       nightly-prerelease: timeout-minutes: 10
4. Документировать в CONTRIBUTING.md, что таймауты намеренно tight — если job
   не укладывается, это сигнал к рефакторингу тестов, а не к увеличению лимита.
```

---

### 🟢 B-22 — Синхронизировать `release-drafter.yml` с фактическим availability Docker

**PR title:** `docs(release-drafter): drop docker pull until B-08 ships`

```
.github/release-drafter.yml строка 25:
    docker pull ghcr.io/reider85/oryaagent:$RESOLVED_VERSION

Но образа в ghcr.io нет (B-08 не выполнен). Пользователь, читающий release notes,
попытается docker pull и получит 404.

Что сделать:
1. Если B-08 ещё не слит — убрать блок "## Docker" из release-drafter.yml template.
2. После мерджа B-08 — вернуть блок, но с fallback:
       ## Docker

       ```bash
       docker pull ghcr.io/reider85/oryaagent:$RESOLVED_VERSION
       # или, если нужны оба UI:
       docker pull ghcr.io/reider85/oryaagent:latest
       ```
3. В README badges заменить `?include_prereleases` на конкретный channel: stable
   и pre-release отдельно.
```

---

## 3. Принцип 20/80 — что даст максимальный эффект

Применённая логика: для каждого улучшения оцениваем **「усилие」** (S/M/L) и **「эффект на надёжность
CI/CD」** (1–5). В таблице ниже — топ-7 изменений, которые вместе покрывают ~80% боли при ~20%
трудозатрат. Сортировка по ratio эффект/усилие.

| # | Изменение | Усилие | Эффект | Ratio | Что даёт |
|---|---|---|---|---|---|
| **1** | **Применить B-01** (починить YAML в docker-compose.yml) | S (15 мин) | 5 | ⭐⭐⭐⭐⭐ | Разблокирует ВСЕ тесты `test_docker_compose.py` (сейчас 0/18 зелёных). Делает CI зеленым. Без этого все остальные правки бесполезны. |
| **2** | **Применить B-08** (build & push Docker в GHCR) | M (1–2 часа) | 5 | ⭐⭐⭐⭐⭐ | Замыкает CD-цикл: тег → образ → пользователь. Сейчас релизные инструкции в release-drafter.yml сломаны. Один job ~30 строк YAML. |
| **3** | **Применить B-04** (`paths-ignore` + dedup для prerelease) | S (20 мин) | 4 | ⭐⭐⭐⭐ | Прекращает спам pre-release тегами. Страница /releases снова читаема. 5 строк YAML. |
| **4** | **Применить B-05** (SHA-pin `pyTooling/Actions/releaser`) + **B-06** (`pull_request` вместо `pull_request_target`) | S (15 мин) | 4 | ⭐⭐⭐⭐ | Закрывает 2 известных attack surface. Security audit пройдёт. |
| **5** | **Применить B-07** (убрать `-x`) + **B-17** (paths-ignore в CodeQL) | S (10 мин) | 3 | ⭐⭐⭐⭐ | Разблокирует видимость всех тестов (а не первого упавшего) + экономит ~10 мин/PR на docs-изменениях. |
| **6** | **Применить B-12** (mypy) + **B-11** (audit gate) | M (3–4 часа) | 4 | ⭐⭐⭐ | Сдвигает обнаружение багов влево: тип-ошибки и CVE ловятся в PR, а не в проде. mypy может дать baseline-мode (warning-only на старте). |
| **7** | **Применить B-21** (timeout-minutes) + **B-15** (artifact retention) | S (15 мин) | 2 | ⭐⭐⭐ | Дисциплина: ни один job не превысит 20 мин, артефакты не переполняют storage. |

**Сумма усилий на топ-7:** ~1 рабочий день (с учётом тестирования правок локально).
**Эффект:** CI зелёный, CD замкнут, security-attack-surface закрыт, видимость тестов полная,
наблюдаемость стабильная. Это и есть 80% результата от 20% усилий.

### Что НЕ делать в первую очередь (отложить до stable CI)

- Векторные фичи: Slack/GitHub-Deployments notifications, custom badges, matrix для 3.14,
  multi-arch Docker builds, SBOM generation. Это даёт <5% надёжности на каждый потраченный час.
- Переписывать workflow на Dagger / Earthfile / CircleCI — текущий GitHub Actions достаточен.
- Внедрять `pre-commit` фреймворк: ruff уже запускается в CI, pre-commit добавит
  overhead без пропорциональной пользы.
- Семантический versioning через `semantic-release` / `commitizen`: release-drafter + labels
  уже покрывает потребность, замена даст marginal gain.

---

## 4. Дополнительные наблюдения (информативные, без обязательства правок)

1. **CODEOWNERS** в корне репо — `GitHub` ищет его в `/.github/CODEOWNERS` **или** `/CODEOWNERS`.
   Сейчас `/CODEOWNERS` — валидно, но нестандартно. Если в `.github/` будут лежать другие файлы,
   рекомендуется перенести в `.github/CODEOWNERS` для единообразия.

2. **`docker-compose.yml` использует `langfuse/langfuse:3` и `langfuse/langfuse-worker:3`**
   без patch-уровня. Минорные релизы Langfuse v3 могут содержать breaking schema changes
   (например, ClickHouse migration). Рекомендуется pin к `3.x.y` после первого боевого теста.

3. **`docker-compose.yml` sampler-proxy build context `../OryaObservability`** — sibling-репозиторий.
   Это значит, что для локального `docker compose up` нужен ещё один клон. CI не проверяет
   presence этого sibling-репо, что приведёт к загадочной ошибке build на свежем clone.
   Добавить в Makefile или README команду `git submodule update --init` (если это submodule),
   либо documented prerequisite.

4. **`release-drafter.yml` autolabeler regex `(?i)^fix.*`** ловит все PR, начинающиеся с `fix`,
   но **не** ловит `bugfix:` или `bug:` префиксы. Conventional commits (`fix:`, `feat:`, `chore:`)
   использовать не удастся без расширения regex.

5. **`SECURITY.md`** ссылается на `https://github.com/Reider85/OryaAgent/security/policy`,
   но в репо нет файла `.github/SECURITY.md` (он в корне). GitHub автоматически подцепит
   `/SECURITY.md` — это OK, но breadcrumb в issue template (`config.yml`) указывает на
   `security/policy` (web URL) — он редиректит на `/security/advisories/new`. Корректно.

6. **`pyproject.toml` classifiers** указывают Python 3.11–3.14, но `requires-python = ">=3.11"`.
   Python 3.14 — пока alpha/beta (зависит от даты). Если CI зелёный на 3.14 — это означает,
   что все deps имеют wheels; иначе matrix-fail. Убедиться, что `langchain-openai>=1.7.2`,
   `langchain-google-genai>=4.4.2` действительно имеют 3.14 wheels.

7. **Makefile использует TABs** (см. `cat -A Makefile`) — стандарт. Но если кто-то отредактирует
   через IDE с "convert tabs to spaces", Makefile сломается. Можно добавить `.editorconfig`:
       [Makefile]
       indent_style = tab

8. **`tests/unit/test_docker_compose.py::test_docker_compose_config_validates`** — единственный
   тест, который проверяет реальную валидность через `docker compose config -q`. Это
   **last line of defense**, но он `pytest.skip` если docker нет на PATH. На CI-раннере
   docker **есть** по умолчанию, но если job runs-on `ubuntu-latest` — это работает. В
   lint-job сейчас docker не гарантирован. Рекомендуется добавить отдельный job
   `compose-validate`, который явно ставит docker через `docker/setup-qemu-action` +
   `docker/setup-buildx-action` (это даст стабильный docker на любом runner).

---

## 5. Чек-лист мерджа (по приоритету)

```text
[ ] B-01  Починить YAML в docker-compose.yml           # CRITICAL — без него CI красный
[ ] B-02  Восстановить test_docker_compose.py           # CRITICAL — regression test
[ ] B-03  Починить compare-URL в release.yml            # HIGH — visible bug в релизах
[ ] B-04  paths-ignore + dedup для prerelease           # HIGH — спам тегами
[ ] B-05  SHA-pin pyTooling/Actions/releaser            # HIGH — supply-chain
[ ] B-06  pull_request вместо pull_request_target       # HIGH — security
[ ] B-07  Убрать -x из pytest                            # HIGH — видимость тестов
[ ] B-08  Docker build & push в GHCR                     # HIGH — замкнуть CD
[ ] B-09  Убрать literal $(date -u) из nightly           # MEDIUM — cosmetic
[ ] B-10  Matrix для integration                         # MEDIUM — coverage
[ ] B-11  pip-audit gate + auto-issue                    # MEDIUM — security
[ ] B-12  mypy в lint                                    # MEDIUM — type safety
[ ] B-13  Consolidate coverage upload                    # MEDIUM — coverage
[ ] B-14  tomllib вместо grep для version                # MEDIUM — robustness
[ ] B-15  Artifact retention-days + gate                 # MEDIUM — storage
[ ] B-16  Ruff cache                                     # LOW — speed
[ ] B-17  paths-ignore в codeql pull_request             # LOW — speed
[ ] B-18  Симметричные stack-up/down                     # LOW — UX
[ ] B-19  Убрать placeholder из release body             # LOW — polish
[ ] B-20  Dependabot для docker-compose                  # LOW — security
[ ] B-21  timeout-minutes на каждый job                  # LOW — discipline
[ ] B-22  Синхронизировать release-drafter с Docker      # LOW — docs accuracy
```

После мерджа B-01 → B-08 → B-04 → B-05/06 → B-07 (в этом порядке) репозиторий получит
зелёный CI, замкнутый CD и закрытые security-attack-surface. Это и есть 20% усилий / 80%
эффекта по CI/CD.

---

*Конец документа CI2.*
