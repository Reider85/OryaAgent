"""Unit tests for A-10 — docker-compose v2 stack structure (no infra needed)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
DOCKERFILE_PATH = REPO_ROOT / "deploy" / "Dockerfile"

INFRA_SERVICES = {"postgres", "redis"}
APP_SERVICES = {"api", "chainlit"}
OBSERVABILITY_SERVICES = {
    "db-init",
    "clickhouse",
    "minio",
    "langfuse",
    "langfuse-worker",
    "sampler-proxy",
}


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _services() -> dict:
    return _compose()["services"]


def test_compose_file_exists():
    assert COMPOSE_PATH.is_file()


def test_required_services_present():
    services = _services()
    expected = INFRA_SERVICES | APP_SERVICES | OBSERVABILITY_SERVICES
    assert expected <= set(services), f"missing services: {expected - set(services)}"


def test_default_profile_starts_infra_only():
    """A bare `docker compose up -d` must stay infra-only (Makefile/quick-start)."""
    for name, service in _services().items():
        profiles = service.get("profiles") or []
        if not profiles:
            assert name in INFRA_SERVICES, (
                f"service {name!r} has no profiles — a bare `docker compose up -d` "
                "would start it; only postgres/redis may do that (A-10)"
            )


def test_app_services_behind_app_profile():
    for name in APP_SERVICES:
        assert _services()[name].get("profiles") == ["app"]


def test_observability_services_behind_observability_profile():
    for name in OBSERVABILITY_SERVICES:
        assert _services()[name].get("profiles") == ["observability"]


def test_api_runs_migrations_then_uvicorn():
    command = _services()["api"]["command"]
    if isinstance(command, list):
        command = " ".join(command)
    assert "orya db migrate" in command, "api container must apply migrations on start"
    assert "uvicorn" in command


def test_api_and_chainlit_share_one_image():
    services = _services()
    assert services["api"]["image"] == "orya-agent:local"
    assert services["chainlit"]["image"] == "orya-agent:local"
    assert "build" in services["api"]
    assert "build" not in services["chainlit"]


def test_api_env_uses_compose_network_hostnames():
    env = _services()["api"]["environment"]
    assert (
        env["DATABASE_URL"]
        == "postgresql://orya:orya_password@postgres:5432/orya_sessions"
    )
    assert env["REDIS_URL"] == "redis://redis:6379"
    assert env["ORYA_SAMPLER_PROXY_URL"] == "http://sampler-proxy:4321"
    assert env["ORYA_MEMORY_DIR"] == "/data/memory"


def test_chainlit_targets_api_service():
    env = _services()["chainlit"]["environment"]
    assert env["ORYA_API_URL"] == "http://api:8000"


def test_healthchecks_defined():
    for name in ("postgres", "redis", "api", "chainlit", "langfuse", "sampler-proxy"):
        assert "healthcheck" in _services()[name], f"{name} must have a healthcheck"


def test_sampler_proxy_builds_from_sibling_repo_and_forwards_to_langfuse():
    service = _services()["sampler-proxy"]
    build = service["build"]
    assert build["context"] == "../OryaObservability"
    assert build["dockerfile"] == "scripts/sampler/Dockerfile"
    assert build["target"] == "sampler-base"
    assert (
        service["environment"]["DOWNSTREAM_URL"]
        == "${SAMPLER_DOWNSTREAM_URL:-http://langfuse:3000}"
    )


def test_langfuse_uses_v3_stack_and_shared_postgres():
    environment = _services()["langfuse"]["environment"]
    assert (
        environment["DATABASE_URL"]
        == "postgresql://orya:orya_password@postgres:5432/langfuse"
    )
    assert environment["CLICKHOUSE_URL"] == "http://clickhouse:8123"
    assert (
        environment["LANGFUSE_INIT_ORG_ID"] == "${LANGFUSE_INIT_ORG_ID:-org-orya-agent}"
    )
    assert _services()["langfuse-worker"]["image"] == "langfuse/langfuse-worker:3"


def test_db_init_creates_langfuse_database_idempotently():
    command = " ".join(_services()["db-init"]["command"])
    assert "pg_database" in command, "db-init must check before CREATE DATABASE"
    assert "CREATE DATABASE langfuse" in command


def test_dockerfile_ships_runtime_deps():
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "ripgrep" in text, "grep/glob tools need the ripgrep binary in the image"
    assert "uv sync --no-dev" in text
    assert "uvicorn" in text
    assert "EXPOSE 8000 8001" in text


@pytest.mark.parametrize("profiles", [(), ("app",)])
def test_docker_compose_config_validates(profiles: tuple[str, ...]):
    """`docker compose config` — guarded: skipped when docker is absent."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker not on PATH")
    args = [docker, "compose"]
    for profile in profiles:
        args.extend(["--profile", profile])
    args.extend(["config", "-q"])
    result = subprocess.run(  # noqa: S603
        args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
