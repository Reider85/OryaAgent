# GITHUB.md — Стратегия GitHub для OryaAgent

> Цель документа: автоматизировать релизы и CI, перевести часть работы на бесплатные ресурсы GitHub, поднять видимость проекта и приток звёзд.
> Документ = аудит + готовые промпты для AI-агента (Cline / Cursor / Copilot Chat / Claude Code), который имеет доступ к локальной копии репозитория `Reider85/OryaAgent`.

---

## 1. Аудит репозитория — что реально есть

### 1.1 Состояние на момент аудита

| Параметр | Значение |
|---|---|
| Репозиторий | `github.com/Reider85/OryaAgent` |
| Звёзды | 1 |
| Форки | 0 |
| Коммиты | 117 |
| Ветки | 1 (`main`) |
| Теги | **0** |
| Релизы | **0** |
| Workflow-файлов `.github/workflows/*.yml` | **0** |
| Версия (`pyproject.toml`) | 7.0.0 |
| Фаза | ALPHA |
| Язык | Python (FastAPI + LangGraph + Chainlit) |

### 1.2 Что уже настроено

- **`pyproject.toml`**:
  - `ruff`: line-length=88, double quotes, isort включён, игноры `E501/B904/W191/B008`, target-version `py311`
  - `pytest`: `asyncio_mode=auto`, `testpaths=["tests"]`, `addopts="-v --tb=short"`, `python_files=["test_*.py","*_test.py"]`
  - build-system: `hatchling`, packages=`["app"]`
  - `requires-python = ">=3.11"`
  - extras `dev`: `pytest`, `pytest-asyncio`, `ruff`
- **`Makefile`**: `make test` → `uv run pytest`, `make lint` → `ruff check .` + `ruff format --check .`, `make format` → `ruff format .`
- **Тестовая структура** (из `AGENTS.md`):
  - `tests/unit` — всегда запускаются, без инфры
  - `tests/integration` — условно (нужны postgres+redis), часть требует `DEEPSEEK_API_KEY`
  - `tests/e2e` — фейковая модель, всегда запускаются
  - `tests/smoke` — канонические задачи со скриптовой фейк-моделью, всегда запускаются
- **`AGENTS.md`** явно пишет: «No mypy/pre-commit/CI exist despite analytics docs claiming so»
- **`README.md`**: бейджи License / Python / Version / Phase / FastAPI / LangGraph / Chainlit / Ruff. **Нет бейджей** CI, coverage, releases, last-commit, stars, Discord.

### 1.3 Чего нет (и это критично)

- Никаких `.github/workflows/*.yml` (проверены `ci.yml`, `main.yml`, `test.yml`, `lint.yml`, `release.yml`, `docker.yml`, `python-package.yml`, `build.yml`, `tests.yml` — все 404)
- Нет `.github/ISSUE_TEMPLATE/`, `CODEOWNERS`, `CONTRIBUTING.md`, `FUNDING.yml`, `SECURITY.md`
- Нет Dependabot, CodeQL, GitHub Pages
- Нет GitHub Releases, тегов, авто-ченджлога
- Нет social preview картинки в настройках репо
- Topics в настройках репо скорее всего пустые или почти пустые

---

## 2. Почему «всегда failed»

В репозитории **физически нет ни одного workflow-файла**. То, что ты видишь как «always failed», — это один из пяти сценариев:

1. **Branch protection / required status checks** ссылаются на имена чеков (например, `CI / lint`), которых не существует. GitHub показывает их как expected/pending, а если они required — PR нельзя смержить, выглядит как «failed».
2. **Старый бейдж в README** ведёт на `https://github.com/Reider85/OryaAgent/actions/workflows/<name>.yml/badge.svg` для несуществующего workflow. GitHub отдаёт серый «no status» или красный «no workflow found».
3. **Кэш UI**: ты раньше добавлял workflow, он упал, ты его удалил, но в списке «All workflows» осталась история красных runs. Без нового файла Actions tab так и будет показывать старые красные запуски.
4. **Внешний сервис** (Codecov, CodeClimate, Snyk, SonarCloud) подключён через GitHub App, но не настроен — шлёт red status на каждый коммит.
5. **Dependabot security alerts** (не Actions, но отображаются красным в Security tab) — это про уязвимости в зависимостях, не про CI.

**Решение**: создать workflow-файлы из Промпта 1 и Промпта 2. После первого зелёного пуша «failed» исчезнет, бейдж станет зелёным.

> Важно: «оптимизировать CI» в твоём случае = «создать CI с нуля», а не «починить существующий». Оптимизация будет в п.3.

---

## 3. Что даст CI и какие тесты запускать

### 3.1 Польза (для звёзд и не только)

| Что даёт CI | Эффект |
|---|---|
| Зелёный бейдж в README | Сигнал качества → +5–15% конверсия visitor→star |
| Block-merge при падении линта/тестов | `main` всегда собирается → доверие контрибьюторов → больше PR |
| Coverage-бейдж +Codecov | Отдельный доверительный сигнал, особенно для enterprise |
| CodeQL (бесплатно для public) | Security-сигнал, обязательный для enterprise-контрибьюторов |
| Авто-релизы в Explore → Releases | ~20–100 просмотров на каждый релиз |
| Dependabot PR | Публичная активность в Insights → Contributors graph |
| Matrix-тестирование Python 3.11/3.12/3.13/3.14 | Поддержка newer Python = wider audience |

### 3.2 Какие тесты запускать в CI (конкретно для OryaAgent)

| Suite | Запуск в CI? | Причина |
|---|---|---|
| `tests/unit` | ✅ всегда, на каждый push/PR | быстрые, без инфры, ~5–15 сек |
| `tests/e2e` | ✅ всегда | фейковая модель, без инфры |
| `tests/smoke` | ✅ всегда | скриптовая фейк-модель, всегда идут |
| `tests/integration` (без live LLM) | ⚠️ в отдельном job с `services: postgres+redis` | реальное покрытие, но +30–60 сек |
| `tests/integration` с live LLM (`DEEPSEEK_API_KEY`) | ❌ в nightly job по cron | платные токены, медленно |
| Ruff check + format check | ✅ всегда | уже есть в Makefile, копируем 1:1 |
| `pip-audit` / `uv pip audit` | ✅ всегда | уязвимости зависимостей, бесплатно |
| `python -m build` (wheel + sdist) | ✅ всегда | проверка, что пакет собирается |
| `python -c "import app"` | ✅ всегда | smoke на циклические импорты |
| CodeQL | ⚠️ отдельно, по cron | security-анализ, ~5–10 мин |

### 3.3 Как оптимизировать (после создания)

- **Кэш `uv`** через `astral-sh/setup-uv@v6` с `enable-cache: true` → установка депов падает с 60 сек до 5 сек
- **Matrix на Python 3.11/3.12/3.13/3.14** параллельно → 4x время, но в 4x контейнеров = реально быстрее wall-clock
- **Разделить на 3 job'а**: `lint`, `unit+e2e+smoke`, `integration` — идут параллельно, каждый падает независимо
- **`fail-fast: false`** в matrix → видишь все упавшие версии, а не только первую
- **Paths filter**: не запускать CI на правки только `*.md` и `docs/`
- **Concurrency group**: отменять старые runs на тот же branch при новом пуше → не тратим минуты
- **Reusable workflow** для lint, чтобы не дублировать между PR и push

### 3.4 Улучшит ли это что-то?

**Для звёзд напрямую — НЕТ.** Звёзды приходят из социальных каналов (HN, Reddit, Twitter, Telegram, dev.to), не из CI.

**Для звёзд косвенно — ДА:**
- Зелёный CI + coverage + security бейджи = +5–15% конверсия visitor→star
- Контрибьюторы охотнее присылают PR (не боятся сломать main) → больше активности → GitHub поднимает репо в поиске
- Авто-релизы = каждый релиз попадает в Explore → Releases → десятки просмотров
- Dependabot PR = постоянная активность в Insights → Contributors graph выглядит живой

---

## 4. Как реально попасть в trending (честно)

GitHub Trending обновляется ежечасно. Алгоритм непубличный, но эмпирические наблюдения:

- Тренд считает **скорость набора звёзд** за период (день/неделя), не абсолютное число
- Порог для топ-25 «Python/Weekly» — обычно 30–80 звёзд за неделю
- Релизы и коммиты **напрямую не влияют** на trending
- Но активность влияет на Explore → «Active repositories» и на общий social proof

### 4.1 Что НЕ работает (предупреждение)

- **Авто-релиз на каждый коммит** — спам в releases feed, GitHub может снизить видимость, пользователи отписываются от watch. **Именно поэтому в Промпте 2 — prerelease на push, full release только на тег**.
- Искусственные звёзды (buy stars) — бан репозитория
- Бот-коммиты «update README» каждый час — GitHub помечает как suspicious activity
- Подписные боты в issues — бан

### 4.2 Что работает

1. **Один содержательный релиз в неделю** с хорошими release notes → попадание в Releases explore
2. **Качественный README**: GIF-демо вверху, сравнительная таблица с конкурентами (aider, continue, cline, opencode), блок «Why OryaAgent?»
3. **Topics** в настройках репо: `ai-agent`, `coding-agent`, `langgraph`, `fastapi`, `chainlit`, `llm`, `developer-tools`, `self-hosted`, `python` — 15–20 topics
4. **Social preview** (PNG 1280×640) в настройках репо → красивая карточка при шеринге в соцсети
5. **Запуск на Hacker News** (Show HN), Reddit `r/programming`, `r/LocalLLaMA`, `r/Python`, dev.to
6. **Telegram-каналы** по AI/Python (русское комьюнити — отдельный буст)
7. **Cross-link**: упомянуть в issues других репо (без спама), ответить на StackOverflow со ссылкой
8. **Conventional Commits** + auto-changelog = каждый релиз автоматически красивый

### 4.3 Рекомендуемая стратегия релизов

- На каждый **push в `main`** → авто-**prerelease** с тегом `v7.0.0-dev.{run_number}+{short_sha}`. Не двигает указатель «latest», не спамит подписчиков, но **мелькает в Releases feed**.
- На каждый **tag `v*.*.*`** → авто-**release** с changelog из conventional commits → двигает «latest», попадает в Explore → Releases.
- Это даёт «мелькание» без спама. Если хочется мелькать ещё чаще — добавь nightly build по cron (Промпт 2 опционально включает это).

---

## 5. Что использует ресурсы GitHub вместо твоих

| Инструмент | Что делает | Лимит для публичного репо |
|---|---|---|
| **GitHub Actions** | CI, релизы, авто-задачи | 2000 мин/мес на бесплатном аккаунте; **публичные репо — безлимитно на Linux runners** |
| **Dependabot** | PR на обновление зависимостей | безлимит |
| **CodeQL** | security-анализ кода | безлимит для public |
| **GitHub Pages** | хостинг доки/сайта | безлимит для public |
| **GHCR (ghcr.io)** | хостинг Docker-образов | 500MB для пабликов |
| **GitHub Releases** | хостинг артефактов релиза | безлимит |
| **Issue/PR templates + Actions auto-label** | автоматизация триажа | безлимит |
| **Projects v2** | канбан-доска | безлимит |

> Главный вывод: для публичного репо GitHub Actions **безлимитны**. Можно крутить matrix на 4 версии Python × 3 ОС и не считать минуты.

---

## 6. Готовые промпты

> **Как использовать**: копируй каждый промпт целиком (вместе с заголовком «Промпт N») и вставляй в AI-агента (Cline / Cursor / Copilot Chat / Claude Code), который имеет доступ к локальной копии репозитория `OryaAgent`. Промпты независимы — можно выполнять в любом порядке или параллельно. Рекомендованный порядок: 1 → 2 → 5 → 4 → 7 → 3 → 6 → 8.

---

### Промпт 1. Базовый CI — починить «always failed» и поставить зелёный бейдж

```
Ты работаешь в репозитории OryaAgent (Python, FastAPI + LangGraph + Chainlit, менеджер пакетов uv, линтер ruff). В репозитории сейчас нет ни одного GitHub Actions workflow — из-за этого в Actions tab висят старые красные запуски, а бейдж CI в README показывает "no workflow".

Задача: создать минимальный, но полноценный CI, который запускается на каждый push в main и на каждый PR, и проходит за <90 секунд на публичном GitHub-hosted runner (ubuntu-latest).

Шаги:

1. Создай файл `.github/workflows/ci.yml` со следующим содержанием (адаптируй имена под реальную структуру, если нужно):

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

# Отменять старые запуски на тот же branch — экономит минуты GitHub
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  lint:
    name: Lint (ruff)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"
      - name: Install deps
        run: uv sync --frozen --no-dev --extra dev
      - name: Ruff check
        run: uv run ruff check .
      - name: Ruff format check
        run: uv run ruff format --check .

  test-fast:
    name: Tests (unit + e2e + smoke)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Setup uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"
      - name: Install deps
        run: uv sync --frozen
      - name: Import smoke (ловим циклические импорты)
        run: uv run python -c "import app; print('import OK')"
      - name: Run unit + e2e + smoke
        run: uv run pytest tests/unit tests/e2e tests/smoke -x --tb=short
        env:
          CI: "true"

  build-check:
    name: Build wheel + sdist
    runs-on: ubuntu-latest
    needs: [lint, test-fast]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Setup uv
        uses: astral-sh/setup-uv@v6
      - name: Install deps
        run: uv sync --frozen
      - name: Build
        run: uv run python -m build
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
          retention-days: 7
```

2. Если в репозитории нет файла `.gitignore` для `.venv/`, `dist/`, `build/`, `*.egg-info/`, `__pycache__/` — добавь их (сверься с существующим .gitignore, не дублируй).

3. Добавь в самый верх `README.md`, сразу после заголовка проекта, строку с бейджем:
   `[![CI](https://github.com/Reider85/OryaAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/Reider85/OryaAgent/actions/workflows/ci.yml)`

4. Закоммить: `git add .github/workflows/ci.yml README.md && git commit -m "ci: add basic lint+test+build pipeline (closes always-failed)"`

5. Запушь в main и проверь:
   - В Actions tab появился workflow «CI»
   - Все три job'а (lint, test-fast, build-check) зелёные
   - Бейдж в README через 30–60 секунд стал зелёным

Если что-то падает — не маскируй ошибку, исправь корневую причину (например, если ruff находит новые нарушения — запусти `uv run ruff format .` и `uv run ruff check --fix .`, закоммить правки, запуши снова).

После успеха напиши короткий отчёт: что создал, сколько секунд занял CI, какой URL бейджа.
```

---

### Промпт 2. Авто-релизы на каждый push (prerelease) + на тег (full release)

```
Ты работаешь в репозитории OryaAgent. Сейчас в нём 0 релизов и 0 тегов. Цель: автоматически создавать релиз при каждом push в main (как prerelease, чтобы не двигать указатель "latest" и не спамить подписчиков) И полноценный release при пуше тега v*.*.* (с ченджлогом из conventional commits).

Стратегия (объясни её пользователю в финальном сообщении):
- push в main → prerelease с тегом `v<pyproject-version>-dev.<run_number>+<short_sha>` → мелькает в Releases feed, но не становится "latest"
- push tag `v7.1.0` → полный release с auto-generated changelog → становится "latest", попадает в Explore → Releases
- nightly по cron (опционально) — отдельный prerelease "nightly" для самых смелых юзеров

Шаги:

1. Создай файл `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    branches: [main]
    tags: ["v*.*.*"]
  workflow_dispatch:
    inputs:
      prerelease:
        description: "Mark as prerelease"
        default: "true"

permissions:
  contents: write   # нужно для создания тегов и релизов

jobs:
  prerelease-on-push:
    name: Prerelease (push to main)
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # нужна история для changelog

      - name: Read version from pyproject.toml
        id: ver
        run: |
          VERSION=$(grep -m1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')
          SHORT_SHA=$(git rev-parse --short HEAD)
          TAG="v${VERSION}-dev.${GITHUB_RUN_NUMBER}+${SHORT_SHA}"
          echo "version=$VERSION" >> $GITHUB_OUTPUT
          echo "tag=$TAG" >> $GITHUB_OUTPUT
          echo "Resolved tag: $TAG"

      - name: Create prerelease
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ steps.ver.outputs.tag }}
          name: "Pre-release ${{ steps.ver.outputs.tag }}"
          body: |
            Automated prerelease from commit ${{ github.sha }}

            Branch: ${{ github.ref_name }}
            Commit: ${{ github.event.head_commit.message }}

            Full changelog: https://github.com/${{ github.repository }}/compare/...${{ github.event.before }}
          prerelease: true
          generate_release_notes: true
          make_latest: "false"

  release-on-tag:
    name: Release (tag v*.*.*)
    if: startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup uv
        uses: astral-sh/setup-uv@v6

      - name: Build dist
        run: |
          uv sync --frozen
          uv run python -m build

      - name: Create release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            dist/*.whl
            dist/*.tar.gz
          generate_release_notes: true   # auto-changelog из PR/commit titles
          make_latest: "true"
          draft: false
          body: |
            ## OryaAgent ${{ github.ref_name }}

            ### Highlights
            (заполни вручную или доверь auto-generated notes ниже)

            ### Installation
            ```bash
            uv tool install orya-agent==${{ github.ref_name }}
            # или
            pip install orya-agent==${{ github.ref_name }}
            ```

            ---
```

2. (Опционально) Создай файл `.github/workflows/nightly.yml` для ежедневного prerelease в 03:00 UTC — это даёт «активность» в Insights, не нагружая тебя:

```yaml
name: Nightly

on:
  schedule:
    - cron: "0 3 * * *"   # 03:00 UTC каждый день
  workflow_dispatch:

permissions:
  contents: write

jobs:
  nightly-prerelease:
    if: github.repository == 'Reider85/OryaAgent'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Resolve tag
        id: ver
        run: |
          VERSION=$(grep -m1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')
          DATE=$(date -u +%Y%m%d)
          SHORT_SHA=$(git rev-parse --short HEAD)
          echo "tag=nightly-${DATE}-${SHORT_SHA}" >> $GITHUB_OUTPUT
          echo "version=$VERSION" >> $GITHUB_OUTPUT

      - name: Create/update nightly release
        uses: pyTooling/Actions/releaser@main
        with:
          tag: ${{ steps.ver.outputs.tag }}
          name: "Nightly ${{ steps.ver.outputs.tag }}"
          prerelease: true
          make_latest: "false"
          body: |
            Nightly build from main @ ${{ steps.ver.outputs.tag }}

            Версия pyproject: ${{ steps.ver.outputs.version }}
            Дата: $(date -u)

            > Это автоматически собранный nightly-билд. Используй на свой риск.
```

3. Закоммить и запушь:
   `git add .github/workflows/release.yml .github/workflows/nightly.yml && git commit -m "ci: auto-prerelease on push + full release on tag v*.*.*"`

4. Проверь:
   - После пуша в main в течение ~60 сек в Releases tab должен появиться prerelease с тегом `v7.0.0-dev.<run_number>+<sha>`, помеченный как "Pre-release"
   - Указатель "latest" НЕ должен сдвинуться (всё ещё нет ни одного full release)
   - Создай тестовый тег: `git tag v7.0.1 && git push origin v7.0.1` → должен появиться полный release с wheel/sdist артефактами, помеченный как "latest"

5. В финальном сообщении объясни пользователю:
   - почему prerelease на push НЕ спамит подписчиков (make_latest: false)
   - что full release нужно делать вручную через `git tag v1.2.3 && git push origin v1.2.3`
   - что nightly-билд можно отключить, удалив nightly.yml
```

---

### Промпт 3. Расширенное тестирование в CI: matrix + coverage + интеграционные тесты

```
Ты работаешь в репозитории OryaAgent. В нём уже есть базовый CI (см. .github/workflows/ci.yml из предыдущего шага). Сейчас нужно расширить: matrix-тестирование на 4 версиях Python, coverage с Codecov, интеграционные тесты с postgres+redis через GitHub Actions services.

Шаги:

1. Замени (или расширь) `.github/workflows/ci.yml`, добавив matrix и coverage. Финальная структура:

```yaml
name: CI

on:
  push:
    branches: [main]
    paths-ignore:
      - "**.md"
      - "docs/**"
      - "LICENSE"
  pull_request:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  test-matrix:
    name: Tests (Python ${{ matrix.python-version }})
    needs: lint
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12", "3.13", "3.14"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          python-version: ${{ matrix.python-version }}
      - run: uv sync --frozen --extra dev
      - run: uv run python -c "import app"
      - name: Run unit+e2e+smoke with coverage
        run: uv run pytest tests/unit tests/e2e tests/smoke --cov=app --cov-report=xml --cov-report=term-missing -x
        env:
          CI: "true"
      - name: Upload coverage to Codecov
        if: matrix.python-version == '3.12'
        uses: codecov/codecov-action@v5
        with:
          files: ./coverage.xml
          fail_ci_if_error: false
          token: ${{ secrets.CODECOV_TOKEN }}   # опционально, без токена тоже работает для public

  integration:
    name: Integration (postgres+redis)
    needs: lint
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: orya
          POSTGRES_PASSWORD: orya
          POSTGRES_DB: orya_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U orya"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
      redis:
        image: redis:7
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      DATABASE_URL: postgresql+asyncpg://orya:orya@localhost:5432/orya_test
      REDIS_URL: redis://localhost:6379/0
      ORYA_ENV: dev
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --frozen
      - name: Run migrations
        run: uv run python -m app.db.migrate
      - name: Run integration tests (без live LLM)
        run: uv run pytest tests/integration -x --tb=short -k "not live"
        env:
          CI: "true"
          DEEPSEEK_API_KEY: ""   # явно пустой — live-тесты должны скипаться

  audit:
    name: Security audit (pip-audit)
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      - name: Audit dependencies
        run: uv run pip-audit --strict
        continue-on-error: true   # предупреждаем, но не блокируем

  build:
    name: Build dist
    needs: [test-matrix, integration]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      - run: uv run python -m build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
```

2. Если `pip-audit` не в dev-зависимостях — добавь в `pyproject.toml` в `[project.optional-dependencies] dev`:
   `"pip-audit>=2.7",`
   И в `[dependency-groups] dev` то же самое.

3. Если в `pyproject.toml` нет `pytest-cov` — добавь:
   `"pytest-cov>=4.1",`

4. После пуши:
   - В Actions tab должны идти 4 параллельных test-matrix job'а + 1 integration + 1 audit
   - Wall-clock время всего CI должно остаться <3 минут благодаря параллелизму
   - Codecov: зарегистрируйся на codecov.io, подключи репо, добавь `CODECOV_TOKEN` в GitHub Secrets (опционально)

5. В финальном отчёте напиши:
   - сколько времени занимает каждый job
   - какие версии Python реально прошли (3.14 может падать — это нормально, он в beta)
   - какой % покрытия посчитал coverage
   - почему pip-audit — `continue-on-error: true` (предупреждаем, не блокируем — иначе заблокирует любой PR с обновлением депов, где есть CVE без патча)
```

---

### Промпт 4. Бейджи + Topics + Social Preview — для discovery и звёзд

```
Ты работаешь в репозитории OryaAgent. Сейчас в README 8 бейджей, но нет CI/coverage/releases/last-commit бейджей. Topics в настройках репо скорее всего пустые. Social preview нет. Это всё дёргает GitHub для показа карточки при шеринге.

Задача: добавить недостающие бейджи в README, подготовить файл с инструкцией для Topics и Social preview (вручную через GitHub UI — их нельзя менять через файлы).

Шаги:

1. В самый верх README.md, сразу после заголовка `# OryaAgent`, добавь блок бейджей (одной строкой с переносами):

```markdown
[![CI](https://github.com/Reider85/OryaAgent/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Reider85/OryaAgent/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Reider85/OryaAgent?include_prereleases&sort=semver)](https://github.com/Reider85/OryaAgent/releases)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Code style: Ruff](https://img.shields.io/badge/Code%20style-Ruff-000.svg)](https://docs.astral.sh/ruff/)
[![GitHub stars](https://img.shields.io/github/stars/Reider85/OryaAgent?style=social)](https://github.com/Reider85/OryaAgent/stargazers)
[![GitHub last commit](https://img.shields.io/github/last-commit/Reider85/OryaAgent)](https://github.com/Reider85/OryaAgent/commits/main)
[![GitHub commits since latest release](https://img.shields.io/github/commits-since/Reider85/OryaAgent/latest)](https://github.com/Reider85/OryaAgent/releases)
[![Codecov](https://img.shields.io/codecov/c/github/Reider85/OryaAgent)](https://codecov.io/gh/Reider85/OryaAgent)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/w/Reider85/OryaAgent)](https://github.com/Reider85/OryaAgent/graphs/commit-activity)
[![GitHub repo size](https://img.shields.io/github/repo-size/Reider85/OryaAgent)](https://github.com/Reider85/OryaAgent)
[![Phase: ALPHA](https://img.shields.io/badge/Phase-ALPHA-orange.svg)](#roadmap--phases)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-blueviolet.svg)](https://github.com/langchain-ai/langgraph)
[![Chainlit](https://img.shields.io/badge/Chainlit-2.0+-orange.svg)](https://chainlit.io/)
```

Если какие-то бейджи уже есть — не дублируй, замени старые на эти (новые с правильными ссылками).

2. Сразу под бейджами добавь «hero»-блок — короткое описание + 1 GIF/скриншот (если его нет, оставь комментарий-плейсхолдер):

```markdown
> Senior Python coding agent with UI and long-term memory. FastAPI + LangGraph + Chainlit. Self-hosted, 30+ LLM providers, production-grade observability.

![OryaAgent demo](docs/assets/demo.gif)

## Why OryaAgent?

| Feature | OryaAgent | aider | continue | cline | opencode |
|---|---|---|---|---|---|
| Self-hosted, no telemetry | ✅ | ✅ | ❌ | ❌ | ❌ |
| Long-term memory (MD files) | ✅ 6 files | ❌ | ⚠️ | ❌ | ❌ |
| UI (Chainlit) | ✅ | ❌ | ✅ (VSCode) | ✅ (VSCode) | ❌ |
| Permission gate on destructive ops | ✅ | ❌ | ⚠️ | ✅ | ❌ |
| 30+ LLM providers | ✅ | ✅ | ✅ | ✅ | ✅ |
| Cost-aware routing | ✅ | ❌ | ❌ | ❌ | ❌ |
| Tiered model routing | ✅ | ❌ | ❌ | ❌ | ❌ |
| Connection pooling per provider | ✅ | ❌ | ❌ | ❌ | ❌ |

> Заполни таблицу реальными данными перед публикацией — это ключевой элемент для звёзд.
```

3. Создай файл `docs/TOPICS_AND_SOCIAL_PREVIEW.md` с инструкцией для тебя же (то, что нельзя автоматизировать через файлы):

```markdown
# Topics & Social Preview — настройка вручную

## Topics (кнопка ⚙ на главной странице репо)

Зайди на https://github.com/Reider85/OryaAgent → справа от About нажми ⚙ → в поле "Topics" добавь:

ai-agent, coding-agent, ai-coding-assistant, langgraph, fastapi, chainlit, llm, llm-agent, 
self-hosted, developer-tools, python, python3, agent, autonomous-agents, long-term-memory,
ai, assistant, chatbot, code-assistant, prompt-engineering, mcp

Это даст ~20 topics — максимум, что распознаёт GitHub для discovery.

## Social Preview (карточка при шеринге в Twitter/Telegram/Slack)

Зайди в Settings → Social preview → Upload → загрузи PNG 1280×640 (до 1MB).

Что должно быть на картинке:
- Логотип/название OryaAgent крупно
- Подзаголовок: "Self-hosted Python coding agent with long-term memory"
- 3-4 иконки фич: LangGraph, FastAPI, Chainlit, 30+ LLM providers
- Тёмный фон + акцентный цвет (фиолетовый/зелёный)

Если картинки нет — сгенерируй её через любой AI image tool (1280x640, dark theme).

## Description и URL

В том же ⚙ окне:
- Description: "Senior Python coding agent with UI and long-term memory. FastAPI + LangGraph + Chainlit."
- Website: укажи ссылку на GitHub Pages (после Промпта 8) или на свой демо-сайт

## Releases feed

Убедись, что в Settings → Features → галочка "Releases" включена.
```

4. Закоммить: `git add README.md docs/TOPICS_AND_SOCIAL_PREVIEW.md && git commit -m "docs: add CI/release/coverage/stars badges + topics guide + social preview checklist"`

5. После этого ручного шага (зайди на GitHub и сделай то, что описано в docs/TOPICS_AND_SOCIAL_PREVIEW.md) — карточка репо будет красиво выглядеть при шеринге в соцсетях.

6. В финальном отчёте подтверди: какие бейджи добавлены, какие topics надо вписать, какой размер social preview нужен.
```

---

### Промпт 5. Dependabot + CodeQL — бесплатные ресурсы GitHub

```
Ты работаешь в репозитории OryaAgent. Цель: включить бесплатные GitHub-сервисы (Dependabot и CodeQL), которые работают на стороне GitHub, не требуют твоих ресурсов и создают видимость активной разработки в Insights → Contributors graph.

Шаги:

1. Создай файл `.github/dependabot.yml`:

```yaml
version: 2

updates:
  # Python dependencies (uv.lock + pyproject.toml)
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "06:00"
      timezone: "Europe/Moscow"
    open-pull-requests-limit: 5
    labels: ["dependencies", "python"]
    commit-message:
      prefix: "deps"
      include: "scope"
    groups:
      python-dev:
        patterns: ["pytest*", "ruff*", "pip-audit*"]
        update-types: ["minor", "patch"]
      python-prod:
        patterns: ["*"]
        exclude-patterns: ["pytest*", "ruff*", "pip-audit*"]
        update-types: ["patch"]   # minor/major — отдельными PR

  # GitHub Actions versions
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    labels: ["dependencies", "github-actions"]
    commit-message:
      prefix: "ci"
      include: "scope"

  # Docker base images (deploy/Dockerfile)
  - package-ecosystem: "docker"
    directory: "/deploy"
    schedule:
      interval: "monthly"
    open-pull-requests-limit: 3
    labels: ["dependencies", "docker"]
```

2. Создай файл `.github/workflows/codeql.yml`:

```yaml
name: CodeQL

on:
  push:
    branches: [main]
    paths-ignore:
      - "**.md"
      - "docs/**"
  pull_request:
    branches: [main]
  schedule:
    - cron: "0 4 * * 1"   # каждый понедельник 04:00 UTC
  workflow_dispatch:

permissions:
  contents: read
  security-events: write
  actions: read

jobs:
  analyze:
    name: Analyze (Python)
    runs-on: ubuntu-latest
    timeout-minutes: 30
    strategy:
      fail-fast: false
      matrix:
        language: ["python"]
    steps:
      - uses: actions/checkout@v4
      - name: Initialize CodeQL
        uses: github/codeql-action/init@v3
        with:
          languages: ${{ matrix.language }}
          queries: +security-and-quality
      - name: Autobuild
        uses: github/codeql-action/autobuild@v3
      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v3
        with:
          category: "/language:${{ matrix.language }}"
```

3. (Опционально) Создай файл `.github/workflows/labels.yml` для авто-создания набора labels в issues/PR — это тоже активность в Insights:

```yaml
name: Sync labels

on:
  push:
    branches: [main]
    paths: [".github/labels.yml"]
  workflow_dispatch:

permissions:
  issues: write

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: crazy-max/ghaction-github-labeler@v5
        with:
          yaml-file: .github/labels.yml
          skip-delete: false
```

И файл `.github/labels.yml` с примерным набором:

```yaml
- name: "bug"
  color: "d73a4a"
  description: "Something isn't working"
- name: "documentation"
  color: "0075ca"
- name: "duplicate"
  color: "cfd3d7"
- name: "enhancement"
  color: "a2eeef"
- name: "good first issue"
  color: "7057ff"
- name: "help wanted"
  color: "008672"
- name: "question"
  color: "d876e3"
- name: "dependencies"
  color: "0366d6"
- name: "python"
  color: "3572A5"
- name: "github-actions"
  color: "2088FF"
- name: "docker"
  color: "0db7ed"
- name: "release"
  color: "006b75"
- name: "security"
  color: "b60205"
```

4. Закоммить всё: `git add .github/ && git commit -m "ci: enable Dependabot + CodeQL + label sync (free GitHub-side resources)"`

5. После пуша:
   - Dependabot начнёт присылать PR'ы на обновление библиотек в ближайшие 24 часа → активность в Insights
   - CodeQL запустится на следующем пуше и/или в понедельник 04:00 UTC → результаты в Security tab
   - Labels синхронизируются сразу после пуша

6. В финальном отчёте:
   - какие экосистемы покрыл Dependabot (pip, github-actions, docker)
   - когда ждать первые PR от Dependabot (обычно в течение суток)
   - где смотреть результаты CodeQL (Security → Code scanning alerts)
```

---

### Промпт 6. Issue/PR templates + CONTRIBUTING + CODEOWNERS + SECURITY

```
Ты работаешь в репозитории OryaAgent. Цель: сделать репо «дружелюбным» к контрибьюторам — это напрямую влияет на звёзды (посетитель видит, что проект серьёзный, и охотнее ставит star).

Шаги:

1. Создай `.github/ISSUE_TEMPLATE/bug_report.yml`:

```yaml
name: Bug report
description: Report a bug
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for taking the time to file a bug report!
  - type: textarea
    id: what-happened
    attributes:
      label: What happened?
      description: A clear description of the bug.
      placeholder: "When I run `orya ...`, then ..."
    validations:
      required: true
  - type: dropdown
    id: component
    attributes:
      label: Component
      options:
        - CLI (`orya`)
        - FastAPI app
        - Chainlit UI
        - LLM provider seam
        - Memory (MD files)
        - Permissions
        - Docker / deployment
        - Other
    validations:
      required: true
  - type: input
    id: version
    attributes:
      label: OryaAgent version
      placeholder: "7.0.0"
    validations:
      required: true
  - type: input
    id: python
    attributes:
      label: Python version
      placeholder: "3.12"
  - type: textarea
    id: logs
    attributes:
      label: Logs / stack trace
      render: shell
  - type: textarea
    id: repro
    attributes:
      label: Reproduction steps
      placeholder: |
        1. Run `...`
        2. ...
        3. See error
```

2. Создай `.github/ISSUE_TEMPLATE/feature_request.yml`:

```yaml
name: Feature request
description: Suggest a new feature
labels: ["enhancement"]
body:
  - type: textarea
    id: problem
    attributes:
      label: What problem does this solve?
      placeholder: "I'm always frustrated when ..."
    validations:
      required: true
  - type: textarea
    id: solution
    attributes:
      label: Proposed solution
    validations:
      required: true
  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives considered
```

3. Создай `.github/ISSUE_TEMPLATE/config.yml`:

```yaml
blank_issues_enabled: false
contact_links:
  - name: Ask a question
    url: https://github.com/Reider85/OryaAgent/discussions
    about: Ask questions and discuss with the community
  - name: Security report
    url: https://github.com/Reider85/OryaAgent/security/policy
    about: Report security vulnerabilities privately
```

4. Создай `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## Summary

<!-- 1-2 sentences: what does this PR do? -->

## Type of change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation
- [ ] Refactor / chore

## Checklist

- [ ] `make lint` passes (`ruff check . && ruff format --check .`)
- [ ] `make test` passes (`uv run pytest tests/unit tests/e2e tests/smoke`)
- [ ] If schema change: updated `schema.sql` + new `migrations/NNNN_*.sql` + `alembic/versions/NNNN_*.py` wrapper
- [ ] If new tool: 5 steps from AGENTS.md (app/tools/<name>.py + __init__ + get_tools() + integration test + unit test)
- [ ] If new LLM provider: only YAML in `providers.yaml` / `models.yaml` / `capabilities.yaml` / `pricing.yaml`
- [ ] Commits follow `M-NN: <subject>` or `A-NN: <subject>` convention from AGENTS.md

## Related

<!-- Issues, tickets, plans. Example: Closes #42. Plan: .opencode/plans/A-21-*.md -->
```

5. Создай `CONTRIBUTING.md` в корне:

```markdown
# Contributing to OryaAgent

Thanks for your interest! This is a short guide. Read [AGENTS.md](./AGENTS.md) for the full architecture conventions.

## Quick start

```bash
git clone https://github.com/Reider85/OryaAgent.git
cd OryaAgent
uv sync
docker compose up -d postgres redis
make db-migrate
make dev          # FastAPI on :8000
# в другом терминале:
make ui           # Chainlit on :8001
```

## Before you commit

```bash
make format       # ruff format .
make lint         # ruff check . && ruff format --check .
make test         # uv run pytest
```

CI прогоняет то же самое на каждый PR — если локально зелёно, скорее всего зелёно и в CI.

## Commit convention

- Ticket-based: `M-13: permissions (fail-closed on missing checkpointer)` или `A-20: connection pool (...)`
- Для не-тикетных правок: `chore: ...`, `docs: ...`, `refactor: ...`, `fix: ...`, `ci: ...`
- Одна логическая change = один коммит

## Code style

- Ruff: line-length 88, double quotes, isort, ignore E501/B904/W191/B008
- Без mypy / pyright — пока не добавили
- Модули начинаются с docstring с ticket id: `"""Tool: write - atomic file writer (M-08).`

## Adding things

- **New tool** — 5 шагов из AGENTS.md (app/tools/<name>.py + __init__ re-export + get_tools() + integration test + unit test)
- **New prompt section** — `*_block()` → append в `build_system_prompt` + тест в `tests/unit/test_prompt.py`
- **New LLM provider** — только YAML в `providers.yaml` / `models.yaml` / `capabilities.yaml` / `pricing.yaml` (это YAML-only по архитектуре)
- **Schema change** — три правки: `schema.sql` + новый `migrations/NNNN_*.sql` + `alembic/versions/NNNN_*.py` wrapper (тесты `test_db_schema.py` + `test_alembic.py` ловят расхождения)

## Tests

| Suite | Что тестирует | Когда запускать |
|---|---|---|
| `tests/unit` | чистая логика, без инфры | всегда |
| `tests/e2e` | round trips с фейковой моделью | всегда |
| `tests/smoke` | канонические задачи | всегда |
| `tests/integration` | postgres/redis | после `docker compose up -d postgres redis` |

## Reporting bugs / features

Используй шаблоны в Issues — они подскажут, какие данные нужны.
```

6. Создай `CODEOWNERS` в корне (или `.github/CODEOWNERS`):

```
# По умолчанию — владелец репо
*                        @Reider85

# Критичные зоны — запросить ревью у автора
/app/core/permissions.py @Reider85
/app/core/security.py    @Reider85
/app/db/                 @Reider85
alembic/                 @Reider85
deploy/                  @Reider85
```

7. Создай `SECURITY.md` в корне:

```markdown
# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 7.0.x   | ✅ |
| < 7.0   | ❌ |

## Reporting a vulnerability

**Не открывай public issue для security-уязвимости.**

Вместо этого:
1. Зайди на https://github.com/Reider85/OryaAgent/security/advisories/new
2. Опиши проблему, шаги воспроизведения, impact
3. Ожидай ответа в течение 72 часов

или напиши на `team@orya.ai` с темой `[SECURITY] OryaAgent`.

## What to include

- Версия OryaAgent (`pyproject.toml`)
- Версия Python и ОС
- Минимальный PoC
- Возможный impact (RCE / data leak / auth bypass / etc.)

## Disclosure policy

- Получив репорт, мы подтверждаем получение в течение 72 часов
- Патч выпускаем в течение 30 дней (критические — 7 дней)
- После релиза патча публикуем GitHub Security Advisory с credit (если автор хочет)
```

8. Закоммить всё одним коммитом:
   `git add .github/ CONTRIBUTING.md CODEOWNERS SECURITY.md && git commit -m "docs: add issue/PR templates, CONTRIBUTING, CODEOWNERS, SECURITY"`

9. В финальном отчёте перечисли созданные файлы и что они дают:
   - Issue templates: структурированные баги/фичи → меньше времени на триаж
   - PR template: чеклист перед ревью → меньше сломанных merge
   - CONTRIBUTING: онбординг контрибьюторов → больше PR → больше звёзд
   - CODEOWNERS: авто-запрос ревью → защита критичных зон
   - SECURITY: доверие enterprise-пользователей
```

---

### Промпт 7. Release Drafter — авто-ченджлог по conventional commits + labels

```
Ты работаешь в репозитории OryaAgent. Цель: при каждом merge PR в main автоматически дополнять draft-release заметками, сгруппированными по labels. Когда ты решишь выпустить версию — publish одной кнопкой.

Шаги:

1. Создай файл `.github/workflows/release-drafter.yml`:

```yaml
name: Release Drafter

on:
  push:
    branches: [main]
  pull_request_target:
    types: [opened, reopened, labeled, unlabeled, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  update-draft:
    runs-on: ubuntu-latest
    steps:
      - uses: release-drafter/release-drafter@v6
        with:
          config-name: release-drafter.yml
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

2. Создай файл `.github/release-drafter.yml`:

```yaml
name-template: 'v$RESOLVED_VERSION'
tag-template: 'v$RESOLVED_VERSION'

# Авто-определение версии из conventional commits / labels
template: |
  ## What's changed since $PREVIOUS_TAG

  $CHANGES

  ## Contributors

  $CONTRIBUTORS

  ## Installation

  ```bash
  uv tool install orya-agent==$RESOLVED_VERSION
  # или
  pip install orya-agent==$RESOLVED_VERSION
  ```

  ## Docker

  ```bash
  docker pull ghcr.io/reider85/oryaagent:$RESOLVED_VERSION
  ```

categories:
  - title: 'Breaking'
    label: 'breaking'
  - title: 'New features'
    label: 'enhancement'
  - title: 'Bug fixes'
    label: 'bug'
  - title: 'Security'
    label: 'security'
  - title: 'Documentation'
    label: 'documentation'
  - title: 'Dependencies'
    label: 'dependencies'
  - title: 'CI/CD'
    label: 'github-actions'
  - title: 'Internal'
    label: 'internal'

exclude-labels:
  - 'duplicate'
  - 'question'
  - 'wontfix'

autolabeler:
  - label: 'bug'
    body: ['(?i).*bug.*', '(?i).*fix.*']
    branch: ['fix/.*', 'hotfix/.*']
    title: ['(?i)^fix.*']
  - label: 'enhancement'
    branch: ['feature/.*', 'feat/.*']
    title: ['(?i)^(feat|feature).*']
  - label: 'documentation'
    branch: ['docs/.*']
    title: ['(?i)^docs.*']
    files: ['docs/.*', '*.md']
  - label: 'security'
    title: ['(?i)(security|cve).*']
  - label: 'github-actions'
    files: ['.github/**/*']

# Минорная версия для enhancement, патч для bugfix, мажор для breaking
version-resolver:
  major:
    labels: ['breaking']
  minor:
    labels: ['enhancement']
  patch:
    labels: ['bug', 'security', 'documentation', 'dependencies', 'github-actions', 'internal']
  default: patch
```

3. Закоммить: `git add .github/workflows/release-drafter.yml .github/release-drafter.yml && git commit -m "ci: add release-drafter for auto-changelog by labels"`

4. После пуша:
   - В Releases tab появится draft release "v7.0.1" (или какой résolver вычислит)
   - Каждый merged PR с подходящим label будет добавлять строку в draft
   - Когда решишь выпустить — нажми "Publish release" в Releases UI → создастся тег `v7.0.1` → триггернется `release.yml` из Промпта 2 (если он есть) и приложит wheel/sdist

5. В финальном отчёте:
   - объясни, как release-drafter отличается от auto-prerelease из Промпта 2 (drafter = аккумулирует draft и публикуешь ты вручную; prerelease = каждый пуш делает новый prerelease-tag автоматически)
   - какие labels нужно ставить на PR, чтобы они попали в нужную категорию
   - как работает version-resolver (breaking → major, enhancement → minor, остальное → patch)
```

---

### Промпт 8. GitHub Pages-сайт документации + Docker-образ в GHCR

```
Ты работаешь в репозитории OryaAgent. Цель: поднять сайт документации на GitHub Pages (бесплатный хостинг) И автоматическую сборку Docker-образа в GHCR (ghcr.io) на каждый релиз. Оба — бесплатные ресурсы GitHub, не твои.

Часть A. GitHub Pages с mkdocs-material:

1. Создай файл `mkdocs.yml` в корне:

```yaml
site_name: OryaAgent
site_description: Senior Python coding agent with UI and long-term memory
site_url: https://reider85.github.io/OryaAgent/
repo_name: Reider85/OryaAgent
repo_url: https://github.com/Reider85/OryaAgent
edit_uri: edit/main/docs/

theme:
  name: material
  language: en
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: deep purple
      accent: indigo
      toggle:
        icon: material/weather-night
        name: Switch to dark
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: deep purple
      accent: indigo
      toggle:
        icon: material/weather-sunny
        name: Switch to light
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.expand
    - navigation.top
    - search.suggest
    - search.highlight
    - content.code.copy
    - content.code.annotate

nav:
  - Home: index.md
  - Getting started:
      - Quick start: getting-started/quick-start.md
      - Configuration: getting-started/configuration.md
      - Docker: getting-started/docker.md
  - Architecture:
      - Overview: architecture/overview.md
      - LLM provider seam: architecture/llm-seam.md
      - Memory system: architecture/memory.md
      - Permissions: architecture/permissions.md
  - Reference:
      - CLI: reference/cli.md
      - API: reference/api.md
      - Environment variables: reference/env.md

plugins:
  - search
  - tags

markdown_extensions:
  - admonition
  - codehilite
  - footnotes
  - toc:
      permalink: true
  - pymdownx.superfences
  - pymdownx.tabbed:
      alternate_style: true
  - pymdownx.tasklist:
      custom_checkbox: true
```

2. Создай минимальный `docs/index.md` (если ещё нет), остальные страницы можно оставить как TODO-плейсхолдеры с заголовком и одной строкой "Coming soon".

3. Создай файл `.github/workflows/pages.yml`:

```yaml
name: Pages

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - "README.md"
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install mkdocs-material
        run: pip install mkdocs-material mkdocs-include-markdown-plugin
      - name: Build
        run: mkdocs build --strict
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

4. После пуша: Settings → Pages → Source = "GitHub Actions". Сайт поднимется на `https://reider85.github.io/OryaAgent/`.

Часть B. Docker-образ в GHCR:

5. Создай файл `.github/workflows/docker.yml`:

```yaml
name: Docker

on:
  push:
    tags: ["v*.*.*"]
    branches: [main]
    paths:
      - "deploy/Dockerfile"
      - "app/**"
      - "pyproject.toml"
      - "uv.lock"
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  build-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Docker meta
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=semver,pattern={{major}}
            type=sha,prefix=sha-
            type=raw,value=latest,enable={{is_default_branch}}

      - name: Set up Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build & push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: deploy/Dockerfile
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

6. Закоммить всё:
   `git add mkdocs.yml docs/ .github/workflows/pages.yml .github/workflows/docker.yml && git commit -m "ci: add GitHub Pages docs site + auto-publish Docker image to GHCR"`

7. После пуша:
   - Pages соберётся и задеплоится на `https://reider85.github.io/OryaAgent/`
   - Docker image соберётся и опубликуется в `ghcr.io/reider85/oryaagent:latest` + `:v7.0.0` (на теге) + `:sha-abc1234`

8. В README добавь бейдж и инструкцию:
   `[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue.svg)](https://reider85.github.io/OryaAgent/)`
   
   И в секцию Quick start:
   ```bash
   docker pull ghcr.io/reider85/oryaagent:latest
   docker run -p 8000:8000 -p 8001:8001 ghcr.io/reider85/oryaagent:latest
   ```

9. В финальном отчёте:
   - URL Pages-сайта
   - URL Docker-образа в GHCR
   - какие бейджи добавить (Docs, Docker pull)
   - что все ресурсы бесплатные (public repo → безлимит Actions + GHCR 500MB)
```

---

## Чек-лист внедрения

Выполни промпты по порядку — каждый занимает у AI-агента 5–15 минут:

1. **Промпт 1** (CI базовый) → запуши → проверь, что бейдж зелёный, "failed" исчез
2. **Промпт 2** (Авто-релизы) → запуши в main → должен появиться prerelease
3. **Промпт 5** (Dependabot + CodeQL) → в течение 24 часов начнут приходить PR'ы
4. **Промпт 4** (Бейджи + Topics + Social preview) → добавь бейджи + зайди в GitHub UI для Topics и Social preview
5. **Промпт 7** (Release Drafter) → в Releases tab появится draft с авто-ченджлогом
6. **Промпт 3** (Расширенное тестирование) → matrix 4 версий Python + coverage + интеграция
7. **Промпт 6** (Issue/PR templates + CONTRIBUTING + SECURITY) → репо выглядит профессионально
8. **Промпт 8** (Pages + GHCR Docker) → сайт документации + образ в реестре

После завершения:
- Создай первый full release: `git tag v7.1.0 && git push origin v7.1.0`
- Проверь, что в Releases tab появился full release с wheel/sdist
- Подготовь пост для Show HN + Reddit r/LocalLLaMA + r/Python — это даст реальный трафик на звёзды

## Что точно НЕ делать

- ❌ Создавать релиз на каждый коммит как `latest` (спам → снижение видимости)
- ❌ Покупать звёзды (бан)
- ❌ Бот-коммиты «update README» каждый час (suspicious activity flag)
- ❌ Ломать `make test` локально и надеяться, что CI «как-нибудь пройдёт»
- ❌ Ставить `continue-on-error: true` на основных job'ах CI (только на pip-audit допустимо)

## Ожидаемый эффект (через 4 недели после внедрения)

| Метрика | Сейчас | Через 4 недели |
|---|---|---|
| Звёзды | 1 | 5–15 (без соц.промо), 30–80 (с HN/Reddit-постом) |
| Релизы | 0 | 4–8 prerelease + 1–2 full release |
| Активность в Insights | минимальная | ежедневные Dependabot PR + CodeQL runs |
| Бейджи в README | 8 | 15+ (CI, coverage, releases, last-commit, stars, activity, docs, docker) |
| Документация | только README | GitHub Pages-сайт + README |
| Docker-образ | нет | `ghcr.io/reider85/oryaagent:latest` + версионные теги |
| Security | нет | CodeQL + SECURITY.md + dependabot security alerts |

Главное для звёзд — это **социальный запуск** (HN, Reddit, Telegram). CI/релизы/документация только повышают конверсию visitor→star, но не генерируют трафик сами.
