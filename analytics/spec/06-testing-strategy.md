# Стратегия тестирования OryaAgent

**Документ:** 06-testing-strategy
**Дата:** 20 октября 2026
**Статус:** Draft v0.1
**Связанные документы:** [01-module-contracts.md](01-module-contracts.md), [02-llm-adapter-spec.md](02-llm-adapter-spec.md), [04-tool-contracts.md](04-tool-contracts.md), [05-security-model.md](05-security-model.md)

---

## 0. Назначение

OryaAgent — production-grade LLM-агент. Тестирование такого продукта требует системного подхода: нельзя «погонять руками» и считать готовым. Этот документ фиксирует:

- Слои тестирования (unit, integration, e2e, security, performance)
- Test matrix: что покрывает каждый слой
- Fixtures и test-data стратегию
- Mocking-стратегию для LLM (без live API в CI)
- CI-дизайн: что, где, как часто
- Coverage-цели и качество тестов
- Property-based тестирование для invariant-ов
- Production-readiness критерии

Без этой стратегии тесты превратятся в «то, что написал разработчик в свободное время» — несистематично, с большими дырами.

## 1. Принципы тестирования

### 1.1. Pyramid

```
                    ▲
                    │
                 ┌──┴──┐
                 │ E2E │   ~5% (10-20 тестов)
                 │  3  │   Реальные сценарии, медленно
                 └──┬──┘
                    │
              ┌─────┴─────┐
              │Integration│  ~20% (50-100 тестов)
              │     2     │  Несколько модулей вместе
              └─────┬─────┘
                    │
         ┌──────────┴──────────┐
         │      Unit tests     │  ~75% (200+ тестов)
         │         1           │  Изолированные, быстро
         └─────────────────────┘
```

### 1.2. Fast feedback

- **Unit tests:** <30s на всю suite
- **Integration tests:** <3min на всю suite
- **E2E tests:** <10min на всю suite
- **CI pipeline green time:** <15min

### 1.3. No flaky tests

- Никаких sleep-ов в тестах (используй `asyncio.Event`, `pytest-asyncio` waitFor)
- Никаких real network calls (используй `vcrpy` или `respx`)
- Никаких random-данных без seed (используй `hypothesis` с `derandomize=False`, но с deterministic seed в CI)

### 1.4. Test readability

- **AAA pattern:** Arrange, Act, Assert — каждый тест в этой структуре
- **One assertion per test** — за исключением случаев, где несколько логически связаны
- **Descriptive names:** `test_read_file_with_invalid_encoding_falls_back_to_latin1`
- **Given-When-Then** в сложных integration-тестах

### 1.5. Tests document behavior

Если непонятно, как должен вести себя модуль — посмотри его тесты. Если поведение не описано тестом — его нет (или это баг).

## 2. Слои тестирования

### 2.1. Unit tests

**Цель:** проверить каждый модуль в изоляции. Все внешние зависимости (LLM, FS, subprocess) — mocked.

```
tests/unit/
├── core/
│   ├── test_loop.py                    # agent_loop с FakeLLM
│   ├── test_prompt.py                  # system_prompt_builder
│   ├── test_context.py                 # context_manager
│   ├── test_session.py                 # session_log + projection
│   └── test_events.py                  # SessionEvent Pydantic-модели
├── llm/
│   ├── test_openai_adapter.py          # с VCR-cassettes
│   ├── test_anthropic_adapter.py       # с VCR-cassettes
│   ├── test_ollama_adapter.py
│   ├── test_registry.py
│   └── test_pricing.py
├── tools/
│   ├── test_read.py
│   ├── test_write.py
│   ├── test_edit.py
│   ├── test_bash.py
│   ├── test_grep.py
│   └── test_glob.py
├── permissions/
│   ├── test_engine.py
│   ├── test_policies.py
│   └── test_sensitive.py
└── cli/
    ├── test_repl.py
    ├── test_commands.py
    └── test_render.py
```

### 2.2. Integration tests

**Цель:** проверить взаимодействие нескольких модулей. Реальная FS, mock LLM, mock subprocess где критично.

```
tests/integration/
├── test_workflow_read_edit_run.py      # read → edit → bash run tests
├── test_workflow_grep_find_edit.py     # grep → read → edit
├── test_session_persistence.py          # session save/load/recover
├── test_permission_flow.py              # ask → user response → execute
├── test_llm_adapter_switch.py          # switch providers mid-session
├── test_context_overflow.py            # long session → context truncation
├── test_crash_recovery.py              # kill -9, restart, verify state
├── test_concurrent_sessions.py         # two sessions in parallel
└── test_audit_log.py                   # audit events for all actions
```

### 2.3. E2E tests

**Цель:** проверить полный workflow с real API (если доступен) или comprehensive mock.

```
tests/e2e/
├── test_refactor_workflow.py           # «отрефактори модуль X»
├── test_bug_fix_workflow.py            # «исправь баг из issue Y»
├── test_explore_codebase.py            # «как работает модуль Z?»
├── test_write_tests.py                 # «напиши тесты для функции F»
├── test_debug_failure.py              # «почему падает test T?»
└── test_generate_feature.py            # «добавь endpoint E»
```

### 2.4. Security tests

**Цель:** проверить защиту от известных атак.

```
tests/security/
├── test_prompt_injection_file.py       # malicious instructions в файле
├── test_prompt_injection_bash.py        # malicious instructions в bash output
├── test_command_injection.py            # dangerous bash patterns
├── test_path_traversal.py               # ../../etc/passwd
├── test_token_leakage.py                # API keys в logs
├── test_sensitive_files.py              # .env access
├── test_deny_list_bypass.py             # regex bypass attempts
├── test_audit_tamper.py                 # audit log integrity
└── test_permission_bypass.py            # bypass via edge-cases
```

### 2.5. Performance tests

**Цель:** задетектить регрессии в latency и throughput.

```
tests/perf/
├── test_cold_start.py                  # <500ms до prompt
├── test_large_session_load.py           # 10k events <1s
├── test_streaming_latency.py            # <50ms LLM-token-to-render
├── test_bash_long_output.py             # 1MB stdout <5s
├── test_grep_large_repo.py              # 100k files <10s
└── test_concurrent_tools.py             # 5 parallel tool calls
```

Performance-тесты не падают на CI (только warn), но генерируют отчеты для trend-tracking.

## 3. Test matrix

| Что тестируем | Слой | Fixture | Mocking | Coverage target |
|---|---|---|---|---|
| `agent_loop` основной цикл | unit | FakeLLM | LLMProvider | 95% |
| `agent_loop` с прерыванием | unit | FakeLLM | LLMProvider | 90% |
| `session_log` append/load | unit | InMemoryStore | FS | 90% |
| `session_log` projection | unit | sample events | — | 100% (invariants) |
| `context_manager` truncation | unit | sample messages | — | 85% |
| `permission_engine` decisions | unit | sample rules | — | 100% (invariants) |
| OpenAI adapter | unit | VCR-cassettes | HTTP | 90% |
| Anthropic adapter | unit | VCR-cassettes | HTTP | 90% |
| `read` tool | unit | temp files | — | 85% |
| `write` tool atomicity | unit | temp files | — | 90% |
| `bash` tool | integration | real subprocess | — | 75% |
| `grep` tool | integration | temp repo | — | 80% |
| Session recovery | integration | corrupted JSONL | — | 90% |
| E2E workflows | e2e | temp project dir | optional LLM | n/a |
| Security attacks | security | malicious payloads | — | 100% (specific) |
| Performance regressions | perf | generated data | — | n/a |

**Total target coverage:** 80% для ядра (`src/orya/core/`), 65% для всего репозитория.

## 4. Fixtures и test-data

### 4.1. Fixture-organisation

```
tests/
├── conftest.py                          # общие fixtures
├── fixtures/
│   ├── __init__.py
│   ├── llm.py                           # FakeLLMProvider
│   ├── sessions/                        # sample session JSONLs
│   │   ├── simple_chat.jsonl
│   │   ├── with_tool_calls.jsonl
│   │   ├── long_session.jsonl
│   │   └── corrupted_last_line.jsonl
│   ├── cassettes/                       # VCR-cassettes для LLM
│   │   ├── anthropic_claude35_text_only.yaml
│   │   ├── anthropic_claude35_tool_use.yaml
│   │   ├── openai_gpt4o_text_only.yaml
│   │   ├── openai_gpt4o_tool_call.yaml
│   │   ├── openai_429_rate_limit.yaml
│   │   └── openai_500_server_error.yaml
│   ├── projects/                        # sample working directories
│   │   ├── small_python_project/
│   │   ├── monorepo_subset/
│   │   └── binary_files/
│   ├── security/
│   │   ├── malicious_readme.md         # содержит prompt injection
│   │   ├── env_with_secrets.env
│   │   └── bash_injection_payloads.txt
│   └── golden/                         # golden outputs для regression
│       ├── projection_simple.json
│       └── projection_with_compaction.json
```

### 4.2. FakeLLMProvider

Самый важный fixture. Позволяет тестировать `agent_loop` без реальных API-calls.

```python
# tests/fixtures/llm.py

class FakeLLMProvider:
    """LLM-provider, который возвращает scripted responses."""
    
    def __init__(self, responses: list[LLMResponse | Exception]):
        self._responses = list(responses)
        self.calls: list[LLMRequest] = []
        self._lock = asyncio.Lock()
    
    async def complete(self, req: LLMRequest) -> AsyncIterable[StreamEvent]:
        async with self._lock:
            self.calls.append(req)
            response = self._responses.pop(0)
        
        if isinstance(response, Exception):
            raise response
        
        # Эмулируем streaming events из response
        for token in split_to_tokens(response.text):
            yield StreamEvent(kind="assistant_token", text=token)
        
        for call in response.tool_calls:
            yield StreamEvent(kind="tool_call_start", tool_call_id=call.id, tool_name=call.name)
            # Stream input as JSON deltas
            json_str = json.dumps(call.input)
            for i in range(0, len(json_str), 50):
                yield StreamEvent(kind="tool_call_delta", tool_call_id=call.id, tool_input_delta=json_str[i:i+50])
            yield StreamEvent(kind="tool_call_end", tool_call_id=call.id)
        
        yield StreamEvent(kind="usage_update", input_tokens=response.usage.input_tokens, ...)
        yield StreamEvent(kind="stop", stop_reason=response.stop_reason)
    
    @property
    def name(self) -> str:
        return "fake"
    
    @property
    def models(self) -> list[str]:
        return ["fake-model"]


# Builder for fluent test setup
class FakeLLMBuilder:
    def __init__(self):
        self._responses = []
    
    def text(self, text: str) -> "FakeLLMBuilder":
        self._responses.append(LLMResponse(text=text, tool_calls=[], ...))
        return self
    
    def tool_call(self, name: str, input: dict) -> "FakeLLMBuilder":
        self._responses.append(LLMResponse(
            text="",
            tool_calls=[ToolCall(id=f"call_{len(self._responses)}", name=name, input=input)],
            ...
        ))
        return self
    
    def error(self, error: LLMError) -> "FakeLLMBuilder":
        self._responses.append(error)
        return self
    
    def build(self) -> FakeLLMProvider:
        return FakeLLMProvider(self._responses)
```

Использование:

```python
def test_loop_handles_tool_call():
    llm = (FakeLLMBuilder()
        .tool_call("read", {"path": "README.md"})
        .text("README contains project description")
        .build())
    
    loop = AgentLoop(llm=llm, ...)
    events = [e async for e in loop.run("что в README?")]
    
    assert any(e.kind == "tool_call_start" and e.tool_name == "read" for e in events)
    assert events[-1].kind == "stop"
    assert len(llm.calls) == 2  # первый — tool_call, второй — финальный ответ
```

### 4.3. VCR-cassettes для LLM

Для тестирования адаптеров — реальные HTTP-ответы записаны заранее.

```python
# tests/unit/llm/test_openai_adapter.py


@pytest.mark.vcr()
async def test_openai_text_completion():
    provider = OpenAICompatProvider(
        api_key="test", base_url="https://api.openai.com/v1"
    )
    req = LLMRequest(model="gpt-4o", messages=[Message(role="user", content="Hi")])

    events = [e async for e in provider.complete(req)]

    assert any(e.kind == "assistant_token" for e in events)
    assert events[-1].kind == "stop"
    assert events[-1].stop_reason == "end_turn"
```

VCR-кассеты хранятся в `tests/fixtures/cassettes/`. Запись:

```bash
# 第一次录制
pytest tests/unit/llm/test_openai_adapter.py --record-vcr

# Обновление (когда OpenAI меняет response format)
pytest tests/unit/llm/test_openai_adapter.py --record-vcr=all
```

### 4.4. Sample projects

Для integration и e2e тестов — готовые проекты:

```
tests/fixtures/projects/
├── small_python_project/
│   ├── README.md
│   ├── pyproject.toml
│   ├── src/mypackage/
│   │   ├── __init__.py
│   │   └── main.py
│   └── tests/
│       └── test_main.py
├── monorepo_subset/                    # ~100 файлов, разные языки
│   ├── packages/
│   │   ├── frontend/
│   │   ├── backend/
│   │   └── shared/
│   └── ...
└── binary_files/
    ├── image.png
    ├── archive.zip
    └── executable
```

Тесты копируют проект во tempdir, запускают OryaAgent, проверяют изменения.

### 4.5. Property-based tests

Для invariant-ов (которые должны выполняться для любых input) — `hypothesis`:

```python
# tests/unit/core/test_session.py
from hypothesis import given, strategies as st


@given(events=lists(session_event_strategy(), min_size=1, max_size=50))
def test_projection_never_returns_more_messages_than_events(events):
    log = InMemorySessionLog(events)
    messages = log.to_messages()
    assert len(messages) <= len(events)


@given(events=lists(session_event_strategy()))
def test_session_round_trip_preserves_events(events):
    log = InMemorySessionLog(events)
    serialized = log.serialize()
    restored = InMemorySessionLog.deserialize(serialized)
    assert restored.events() == events
```

Custom strategies:

```python
def session_event_strategy():
    return builds(
        SessionEvent,
        seq=integers(min_value=1),
        ts=datetimes(timezones=timezones()),
        kind=sampled_from(["user_message", "assistant_message", ...]),
        payload=...,
    )
```

## 5. Mocking strategy

### 5.1. Что мокаем

| Зависимость | Mock в unit | Mock в integration | Mock в e2e |
|---|---|---|---|
| LLM Provider | FakeLLMProvider | FakeLLMProvider | Optional real API |
| File System | `tmp_path` (pytest) | `tmp_path` | Real FS in tempdir |
| Subprocess (bash) | Mock with `AsyncMock` | Real subprocess | Real subprocess |
| HTTP (LLM API) | VCR-cassettes | VCR-cassettes | Real API (optional) |
| Time | `freezegun` | `freezegun` (where needed) | Real time |
| Environment vars | `monkeypatch.setenv` | `monkeypatch.setenv` | Real env |

### 5.2. Что НЕ мокаем

- **Pydantic models** — они тонкие, тестировать их излишне
- **Pure functions** (token-counting, path-matching) — тестируем с real implementation
- **Standard library** — `os.path`, `pathlib`, `json` — тестируем с real calls

### 5.3. Anti-patterns

- ❌ Mocking того, что не owned (например, `httpx.Client.get`) — лучше VCR
- ❌ Mocking слишком много слоев — тест становится хрупким
- ❌ Test setup длиннее, чем тест — рефактори fixture
- ❌ Тесты, которые зависят от порядка выполнения — изолируй
- ❌ Sleep в тестах — используй events / polling

## 6. CI/CD дизайн

### 6.1. GitHub Actions workflow

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ruff mypy
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy src/orya
  
  test-unit:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python: ["3.12", "3.13"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "${{ matrix.python }}" }
      - run: pip install -e ".[dev]"
      - run: pytest tests/unit/ --cov=src/orya --cov-report=xml
      - uses: codecov/codecov-action@v4
  
  test-integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest tests/integration/ -v
  
  test-security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest tests/security/ -v
  
  test-e2e:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest tests/e2e/ -v
      # E2E тесты используют FakeLLMProvider по умолчанию
      # Опционально: --live-api для тестов с реальными API (требует secrets)
  
  perf-benchmark:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest tests/perf/ --benchmark-only
      - uses: actions/upload-artifact@v4
        with:
          name: benchmark-results
          path: .benchmarks/
```

### 6.2. Branch protection rules

На `main`:
- ✅ Required: lint, test-unit, test-integration, test-security
- ✅ Required: 1 review approval
- ✅ Required: branches up-to-date before merge
- ❌ Optional: test-e2e, perf-benchmark (для PR без UI-изменений)

### 6.3. Pre-merge checklist

PR author проверяет:
- [ ] Все тесты проходят локально
- [ ] Coverage не упал
- [ ] Добавлены тесты для новой функциональности
- [ ] Нет новых flaky-тестов
- [ ] Documentation обновлена

### 6.4. Nightly run

```yaml
# .github/workflows/nightly.yml
name: Nightly
on:
  schedule:
    - cron: "0 3 * * *"  # 3 AM UTC

jobs:
  full-suite:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[dev]"
      - run: pytest tests/ -v --cov
      - run: pytest tests/e2e/ --live-api  # реальные API-calls
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### 6.5. Release pipeline

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags: ["v*"]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[dev]"
      - run: pytest tests/unit/ tests/integration/ tests/security/
  
  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install build
      - run: python -m build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/*
  
  publish-testpypi:
    needs: build
    runs-on: ubuntu-latest
    environment: testpypi
    steps:
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.TEST_PYPI_TOKEN }}
          repository-url: https://test.pypi.org/legacy/
  
  publish-pypi:
    needs: publish-testpypi
    runs-on: ubuntu-latest
    environment: pypi
    steps:
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_TOKEN }}
  
  github-release:
    needs: publish-pypi
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/*
          generate_release_notes: true
```

## 7. Coverage и метрики

### 7.1. Coverage targets

| Module | Target | Min required |
|---|---|---|
| `src/orya/core/` | 95% | 90% |
| `src/orya/llm/` | 90% | 85% |
| `src/orya/tools/` | 90% | 80% |
| `src/orya/permissions/` | 95% | 90% |
| `src/orya/cli/` | 75% | 65% |
| Total | 80% | 70% |

### 7.2. Quality metrics

Coverage — недостаточен. Дополнительно:

- **Mutation testing** через `mutmut` — измеряет, насколько тесты ловят баги в коде. Цель: mutation score >70%.
- **Test isolation score** — могут ли тесты выполняться в любом порядке? 100% yes.
- **Flaky test rate** — <1% от прогонов. Если выше — investigate.
- **Avg test duration** — unit <100ms, integration <500ms, e2e <30s.

### 7.3. Coverage reporting

```bash
pytest --cov=src/orya --cov-report=html
open htmlcov/index.html
```

В CI — Codecov upload, visible как PR-comment.

## 8. Production-readiness критерии

Перед v0.1.0 release:

- [ ] 100% unit tests passing (3 ОС × 2 Python versions)
- [ ] 100% integration tests passing
- [ ] 100% security tests passing
- [ ] E2E tests passing (с FakeLLM)
- [ ] Coverage ≥ 80% total, ≥ 90% для core
- [ ] Mutation score ≥ 70%
- [ ] 0 flaky tests за последние 30 прогонов
- [ ] Cold start < 500ms
- [ ] LLM-token-to-render < 50ms
- [ ] Documentation complete: README, all specs, ADRs
- [ ] SECURITY.md reviewed
- [ ] LICENSE in place
- [ ] PyPI release tested on TestPyPI
- [ ] Smoke-test с реальными LLM API (Claude, GPT-4o, Ollama)
- [ ] Manual exploratory testing: 10 типичных сценариев

Перед v1.0.0 release (production-grade):

- [ ] 1000+ unit tests
- [ ] 50+ integration tests
- [ ] 20+ e2e tests (с реальными API)
- [ ] External security audit
- [ ] Performance benchmarks (без regression за 3 месяца)
- [ ] 100+ beta users feedback собран и обработан
- [ ] SOC 2 audit started (если enterprise-targeted)
- [ ] Documentation: 0 broken links, 0 TODOs
- [ ] 24/7 monitoring для critical bugs (через Sentry или аналог)

## 9. Test anti-patterns (что НЕ делать)

### 9.1. Anti-pattern: test с реальным LLM в CI

```python
# ❌ плохо
async def test_loop_with_real_llm():
    provider = AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"])
    loop = AgentLoop(llm=provider, ...)
    # Тест падает случайно, тратит деньги, зависит от network
```

```python
# ✅ хорошо
async def test_loop_with_fake_llm():
    provider = FakeLLMBuilder().text("hello").build()
    loop = AgentLoop(llm=provider, ...)
    # Детерминированный, быстрый, бесплатный
```

### 9.2. Anti-pattern: test, проверяющий implementation

```python
# ❌ плохо
def test_loop_calls_llm_once():
    loop = AgentLoop(...)
    await loop.run("hi")
    assert len(loop._llm.calls) == 1  # проверяет internal state
```

```python
# ✅ хорошо
def test_loop_returns_assistant_message():
    loop = AgentLoop(...)
    events = [e async for e in loop.run("hi")]
    assert any(e.kind == "assistant_message" for e in events)
```

### 9.3. Anti-pattern: тест зависит от env

```python
# ❌ плохо
def test_provider_loaded_from_env():
    os.environ["OPENAI_API_KEY"] = "test"
    provider = load_provider()
    assert provider.api_key == "test"  # тест зависит от env
```

```python
# ✅ хорошо
def test_provider_loaded_from_config():
    config = {"api_key_env": "OPENAI_API_KEY"}
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
        provider = load_provider(config)
        assert provider.api_key == "test"
```

### 9.4. Anti-pattern: god-test

```python
# ❌ плохо
def test_loop_works():
    loop = AgentLoop(...)
    events = await loop.run("do everything")
    assert len(events) > 0
    # что проверяет? что не упало? это слишком broadly
```

```python
# ✅ хорошо
async def test_loop_emits_assistant_token_events(): ...


async def test_loop_emits_tool_call_event_for_read(): ...


async def test_loop_stops_after_max_iterations(): ...
```

## 10. Documentation tests

### 10.1. Doctest

```python
# src/orya/core/loop.py
class AgentLoop:
    """Main agent loop.
    
    >>> from orya import AgentLoop, FakeLLMProvider
    >>> loop = AgentLoop(llm=FakeLLMProvider([LLMResponse(text="hi")]))
    >>> asyncio.run(collect(loop.run("hello")))
    ['hi']
    """
```

Doctests запускаются в CI: `pytest --doctest-modules src/`.

### 10.2. README tests

README.md — должен быть исполняемым через `pytest --markdown-docs`:

```markdown
## Quick start

```bash
$ pip install orya
$ orya --version
0.1.0
```
```

Если версия в README не совпадает с реальной — тест падает.

## 11. Открытые вопросы

1. **Live API tests cadence?** Nightly? On-demand? Before release?
2. **Visual regression для TUI?** Скриншоты TUI-state-ов, diff при изменении. v2: `pytest-textual-snapshot`.
3. **Fuzzing infrastructure?** `atheris` для Python fuzzing. MVP: property-based tests. v2: continuous fuzzing.
4. **Chaos engineering?** Случайно убивать subprocess-ы в integration tests. MVP: targeted crash-recovery tests. v2: chaos suite.

---

**Следующие шаги:**

1. Создать `tests/` структуру с `conftest.py` и базовыми fixtures
2. Реализовать `FakeLLMProvider` и `FakeLLMBuilder`
3. Записать VCR-cassettes для основных LLM-сценариев
4. Настроить GitHub Actions CI pipeline
5. Зафиксировать coverage thresholds и quality gates
