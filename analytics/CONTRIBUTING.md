# Contributing to OryaAgent

Спасибо, что рассматриваете вклад в OryaAgent! Этот документ описывает процесс и стандарты, которым мы следуем. Кратко: откройте Issue для обсуждения, форкните репозиторий, сделайте изменения в feature-ветке, откройте PR с описанием и тестами.

## Кодекс поведения

Участие в проекте регулируется [Contributor Covenant 2.1](https://contributor-covenant.org/version/2/1/code_of_conduct/). Участвуя, вы соглашаетесь соблюдать его условия. Нарушения сообщайте через security-каналы (см. SECURITY.md) или напрямую мейнтейнерам.

## Перед стартом

Прочитайте эти документы — без них контрибьюшн будет слепым:

1. [**README.md**](README.md) — общее понимание проекта
2. [**analytics/self-agent.md**](analytics/self-agent.md) — архитектура и принципы
3. [**analytics/spec/01-module-contracts.md**](analytics/spec/01-module-contracts.md) — контракты модулей
4. [**analytics/adr/README.md**](analytics/adr/README.md) — история архитектурных решений

Если ваш вклад меняет одно из архитектурных решений — сначала откройте ADR-discussion issue. Если ваш вклад добавляет новую функциональность — проверьте, не отложена ли она в roadmap.

## Что мы принимаем

### Всегда приветствуются

- **Bug fixes** с тестом, который воспроизводит баг
- **Улучшения документации** — typos, уточнения, новые примеры
- **Новые LLM-адаптеры** — см. спецификацию `02-llm-adapter-spec.md`
- **Улучшения инструментов** в рамках существующих контрактов — см. `04-tool-contracts.md`
- **Тесты** — особенно edge-cases и интеграционные сценарии
- **Performance-оптимизации** с бенчмарками до/после

### Требуют обсуждения в Issue

- **Новые модули** в ядре — это меняет MVP-контракт
- **Изменения публичного API** — breaking changes требуют major-версии
- **Новые зависимости** — см. политику ниже
- **Поддержка новой ОС или архитектуры** — нужна CI-инфраструктура

### Не принимаются без архитектурного обсуждения

- **MCP-клиент и hooks** — отложены на v2 по ADR-005; обсуждение через ADR-discussion
- **Subagents и Task-делегирование** — v3
- **Cron / scheduler / goals+judge** — v3+ (по self-agent.md)
- **Кросс-сессионная память** — v2, требует policy-документа по приватности

## Настройка окружения

```bash
# Клонирование
git clone https://github.com/Reider85/OryaAgent.git
cd OryaAgent

# Создание виртуального окружения (требуется Python 3.12+)
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Установка в режиме разработки с dev-зависимостями
pip install -e ".[dev]"

# Установка pre-commit хуков
pre-commit install

# Проверка, что всё работает
pytest tests/
orya --version
```

## Стандарты кода

### Python

- Версия: **Python 3.12+** (используем улучшенный asyncio, PEP 695 type-parameters, `tomllib`)
- Форматирование: **ruff format** (Black-совместимый)
- Линтер: **ruff check** с конфигурацией в `pyproject.toml`
- Импорты: **isort** через ruff
- Type-checking: **mypy --strict** для ядра, `--check-untyped-defs` для тестов

### Архитектурные ограничения

- **Asyncio first.** Любая I/O операция должна быть async. Синхронные вызовы в hot-path — через `asyncio.to_thread`.
- **Pydantic для всех внешних данных.** Входы/выходы API, конфиги, форматы сессий — валидируются Pydantic-моделями.
- **Без глобального состояния.** Зависимости передаются через конструкторы, не через singleton-ы.
- **Структура пакетов** в `src/orya/` — см. существующий layout.

### Тесты

- **Фреймворк:** pytest + pytest-asyncio
- **Покрытие:** минимум 80% для ядра (`src/orya/core/`), 60% для всего
- **Стиль:** Given-When-Then, именование `test_<unit>_<scenario>_<expected>`
- **Fixture-ы:** в `tests/fixtures/`, переиспользуемые между модулями
- **Mock LLM:** через `FakeLLMProvider` в `tests/fixtures/llm.py` — никак не вызывать реальные API

Каждый PR должен:

1. Проходить все существующие тесты
2. Содержать тесты для новой функциональности
3. Не снижать общий coverage

## Процесс PR

### 1. Создайте Issue (для нетривиальных изменений)

Опишите: что вы хотите сделать, почему, какую проблему решаете. Получите feedback от мейнтейнеров до кодирования — это экономит время обеих сторон.

### 2. Создайте feature-ветку

```bash
git checkout -b feat/my-feature
# или: fix/issue-123, docs/readme-update, refactor/loop-cleanup
```

### 3. Делайте атомарные коммиты

Следуйте [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(llm): add Ollama provider adapter

- New `OllamaProvider` class in `src/orya/llm/providers/ollama.py`
- Local discovery via `ollama list` command
- Tested with llama3.1 and qwen2.5

Closes #142
```

Префиксы: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `perf:`.

### 4. Обновите документацию

Если ваш PR:
- Меняет публичный API → обновите `analytics/spec/`
- Добавляет архитектурное решение → создайте ADR
- Меняет пользовательский интерфейс → обновите `README.md` и `docs/`

### 5. Запустите проверки локально

```bash
pre-commit run --all-files
pytest tests/ -v --cov=src/orya
mypy src/orya
```

### 6. Откройте PR

Шаблон PR включает:

- **Summary** — что и зачем
- **Changes** — список изменений по пунктам
- **Testing** — как тестировали
- **Breaking changes** — да/нет
- **Checklist** — все ли отмечено

PR reviewed в течение 5 рабочих дней. Если ревью затягивается — пингуйте в Discussions.

## Политика зависимостей

### Что можно добавлять без обсуждения

- Зависимости из стандартной экосистемы: `pydantic`, `httpx`, `rich`, `prompt_toolkit`, `click` или `typer`, `pyyaml`
- Dev-зависимости: `pytest`, `mypy`, `ruff`, `pre-commit`

### Что требует обсуждения

- Любая зависимость с native-extensions (compile-time) — это усложняет дистрибуцию
- Anything with GPL/AGPL — несовместимо с Apache-2.0
- Зависимости >10MB в установке — нужна сильная мотивация

### Запрещено

- Зависимости с uncertain licensing
- Anything requiring network on import (должно быть lazy)
- Зависимости для одной minor-фичи, которые тянут 50 транзитивных

## Release process

Релизы выпускаются мейнтейнерами по semver:

- **PATCH** (0.1.0 → 0.1.1): bug fixes, не ломающие API
- **MINOR** (0.1.1 → 0.2.0): новая функциональность, обратно совместимая
- **MAJOR** (0.x → 1.0.0): breaking changes

Release-candidates (0.1.0-rc1) публикуются за 1-2 недели до релиза в TestPyPI. Финальные релизы — в PyPI и GitHub Releases.

Полный checklist релиза — внутренний документ мейнтейнеров; ключевые шаги описаны в [`analytics/distribution-plan.md`](analytics/distribution-plan.md).

## Признание контрибьюций

Все контрибьюторы добавляются в `CONTRIBUTORS.md` при первом merged PR. Significant contributions (architecture, key modules) отмечаются в release notes соответствующей версии.

## Вопросы?

- **Issues** — баги и feature-запросы
- **Discussions** — вопросы по архитектуре, идеи, Q&A
- **Email** (security) — см. SECURITY.md

Мы отвечаем в течение 5 рабочих дней. Если ответа нет — пингуйте ещё раз, иногда Issue теряется.

Спасибо за ваш вклад в OryaAgent! 🚀
