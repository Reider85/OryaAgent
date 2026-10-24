# Plan: M-02 — pydantic-settings config + multi-provider registry

**Status:** ready for execution (blocked: plan mode / edit permissions active)
**Commit message:** `M-02: pydantic-settings config + multi-provider settings merge`
**User decisions:** database_url/redis_url get .env.example-style defaults; commit as separate M-02 commit.

## Current state

- M-00 ✅, M-01 ✅ (LLM seam, YAML registries, importers, /llm/* endpoints)
- `app/core/llm/settings.py` — minimal LLM slice; docstring: "M-02 will absorb this into full Settings"
- `capabilities.yaml`, importers already satisfy M-02 parts (no changes needed)

## Steps

### 1. Create `app/core/config.py`

`Settings(BaseSettings)` (pydantic-settings v2) + moved yaml helpers + `@lru_cache get_settings()`.

- Env aliases via `validation_alias=AliasChoices(...)` (no global env_prefix), `populate_by_name=True`, `env_file=".env"`, `extra="ignore"`.
- Fields:
  - LLM: `llm_provider="anthropic"`, `llm_model="claude-sonnet-3.5"`, `llm_api_key: SecretStr|None`, `llm_base_url: str|None`, `llm_temperature=0.0`, `llm_max_tokens=8192`, `llm_timeout_s=120` (env: `ORYA_LLM_*`)
  - DB: `database_url` (default `postgresql://orya:orya_password@localhost:5432/orya_sessions`; env `DATABASE_URL`/`ORYA_DATABASE_URL`), `database_pool_size=5`, `database_max_overflow=10`
  - `redis_url` (default `redis://localhost:6379`; env `REDIS_URL`)
  - `memory_dir: Path` default `~/.orya/memory/` (validator expands `~`; env `ORYA_MEMORY_DIR`)
  - `permission_policy: Literal["strict","permissive"]="strict"` (env `ORYA_PERMISSION_POLICY`)
  - `log_level="INFO"` (env `LOG_LEVEL`)
  - Future placeholders: `auth_secret_key`, `auth_algorithm="HS256"`, `langsmith_api_key`, `otel_exporter_otlp_endpoint`, `oriahs_url`, `oriahs_timeout_s=30`, `chainlit_port=8000`, `nextjs_port=3000`
- Move from `llm/settings.py`: `ENV_VAR_PATTERN`, `user_config_path()` (ORYA_CONFIG_PATH override), `_expand_env_vars`, `load_user_config`, `load_expanded_user_config`, `llm_block`, `provider_block`, `is_unresolved`.
- YAML fallback merge in `get_settings()`: for fields in `_YAML_FALLBACKS` map, apply `~/.orya/config.yaml` value only when (a) no env var of that field is present in `os.environ` AND (b) value did not come from `.env` (compare `Settings()` vs `Settings(_env_file=None)`). Map:
  - `llm_provider` ← `llm.default_provider`
  - `llm_model` ← `llm.default_model`
  - `database_url`, `redis_url`, `memory_dir`, `permission_policy`, `log_level` ← same-name top-level keys
- `clear_settings_cache()`; lazy module `__getattr__` for `settings` attribute (PEP 562).

### 2. `app/core/llm/settings.py` → re-export shim

`from app.core.config import ENV_VAR_PATTERN, get_settings, is_unresolved, llm_block, load_expanded_user_config, load_user_config, provider_block, user_config_path` + deprecation docstring. Update `factory.py` and `importers.py` to import from `app.core.config` directly.

### 3. `tests/unit/test_config.py`

Autouse fixture: chdir(tmp_path), delete all ORYA_*/DATABASE_URL/REDIS_URL/LOG_LEVEL env vars, point `ORYA_CONFIG_PATH` to tmp, `clear_settings_cache()` before/after.

Tests: defaults; env overrides (ORYA_LLM_PROVIDER, DATABASE_URL, ORYA_PERMISSION_POLICY); yaml fallback (default_provider/default_model; env wins over yaml); `${ENV_VAR}` expansion + `is_unresolved`; `.env` file read; singleton identity; `permission_policy` validation error; SecretStr not in repr; memory_dir `~` expansion; shim exports from `app.core.llm.settings`.

### 4. `.env.example`

Add: `ORYA_LLM_TEMPERATURE/MAX_TOKENS/TIMEOUT_S`, `# ORYA_PERMISSION_POLICY=strict`, `# DATABASE_POOL_SIZE/DATABASE_MAX_OVERFLOW`, `# ORYA_CHAINLIT_PORT`, commented auth/observability/OriaHS placeholders.

### 5. README

- Phase progress: M-02 ✅
- New section «Configuration (M-02)»: priority env/.env → `~/.orya/config.yaml` → defaults; `${ENV_VAR}` example for config.yaml; link to `.env.example`.

### 6. Verify + commit

`uv run pytest tests/unit -q` (все зелёные, включая M-01) → `uv run pytest` full → `uv run ruff check .` → `uv run ruff format --check .` → `git add` app/core/config.py app/core/llm/settings.py app/core/llm/factory.py app/core/llm/importers.py tests/unit/test_config.py .env.example README.md → commit `M-02: pydantic-settings config + multi-provider settings merge`.

## Invariants to preserve

- M-01 factory resolution chain: arg → env → config.yaml → registry default → anthropic/claude-sonnet-3.5 (yaml merge into get_settings() keeps this working since Settings defaults are non-None).
- No plaintext API keys in config.yaml (`is_unresolved` check stays).
- Forbidden: no `os.getenv` outside Settings/config module; no pydantic v1 BaseSettings.
