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
    "clickhouse-obs-init",
    "minio",
    "langfuse",
    "langfuse-worker",
    "sampler-proxy",
    "prometheus",
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


def test_api_env_wires_langfuse_export():
    """A-15: the api container exports spans through the sampler-proxy."""
    env = _services()["api"]["environment"]
    assert env["LANGFUSE_HOST"] == "http://sampler-proxy:4321"
    # Interpolated at deploy time; must match LANGFUSE_INIT_PROJECT_* keys.
    assert env["LANGFUSE_PUBLIC_KEY"] == "${LANGFUSE_PUBLIC_KEY:-pk-lf-orya-agent}"
    assert env["LANGFUSE_SECRET_KEY"] == "${LANGFUSE_SECRET_KEY:-sk-lf-orya-agent}"
    assert env["LANGFUSE_DIRECT_URL"] == "${LANGFUSE_DIRECT_URL:-http://langfuse:3000}"


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


# A-17: Tests for new services and environment variables
def test_clickhouse_obs_init_service():
    """A-17: clickhouse-obs-init service exists and has correct properties."""
    services = _services()
    assert "clickhouse-obs-init" in services

    service = services["clickhouse-obs-init"]
    assert "profiles" in service
    assert "observability" in service["profiles"]

    # Should depend on clickhouse being healthy
    assert "depends_on" in service
    assert "clickhouse" in service["depends_on"]
    assert service["depends_on"]["clickhouse"]["condition"] == "service_healthy"

    # Should be one-time init (no restart)
    assert service.get("restart") == "no"

    # Should have the correct entrypoint
    assert "entrypoint" in service
    # clickhouse-client is in the third element (index 2)
    assert "clickhouse-client" in service["entrypoint"][2]

    # Should mount the SQL init script
    assert "volumes" in service
    sql_mounts = [vol for vol in service["volumes"] if "01_audit_events_hot.sql" in vol]
    assert len(sql_mounts) == 1


def test_prometheus_service():
    """A-17: prometheus service exists and has correct properties."""
    services = _services()
    assert "prometheus" in services

    service = services["prometheus"]
    assert "profiles" in service
    assert "observability" in service["profiles"]

    # Should use the official prometheus image
    assert service["image"] == "prom/prometheus:v3.4.2"

    # Should restart unless stopped
    assert service.get("restart") == "unless-stopped"

    # Should mount the config file
    assert "volumes" in service
    config_mounts = [vol for vol in service["volumes"] if "prometheus.yml" in vol]
    assert len(config_mounts) == 1

    # Should expose the metrics port
    assert "ports" in service
    port_mappings = [port for port in service["ports"] if ":9090" in port]
    assert len(port_mappings) == 1

    # Should have health check
    assert "healthcheck" in service


def test_sampler_proxy_new_environment_variables():
    """A-17: sampler-proxy has new A-17 environment variables."""
    services = _services()
    sampler = services["sampler-proxy"]

    # Should have the new audit-related environment variables
    expected_env_vars = [
        "PROMETHEUS_URL",
        "AGENT_OBS_SAMPLER_AUDIT_ENABLED",
        "CLICKHOUSE_HOST",
        "CLICKHOUSE_PORT",
        "CLICKHOUSE_DB",
        "CLICKHOUSE_USER",
        "CLICKHOUSE_PASSWORD",
    ]

    # Check that these are referenced in the environment
    env_section = sampler.get("environment", {})
    for var in expected_env_vars:
        # The variable should either be set directly or referenced with default
        assert var in env_section or f"${var}" in str(env_section)


def test_sampler_proxy_dependency_on_clickhouse_obs_init():
    """A-17: sampler-proxy depends on clickhouse-obs-init."""
    services = _services()
    sampler = services["sampler-proxy"]

    assert "depends_on" in sampler

    # Should depend on clickhouse-obs-init
    assert "clickhouse-obs-init" in sampler["depends_on"]
    assert (
        sampler["depends_on"]["clickhouse-obs-init"]["condition"]
        == "service_completed_successfully"
    )

    # Should still depend on langfuse
    assert "langfuse" in sampler["depends_on"]
    assert sampler["depends_on"]["langfuse"]["condition"] == "service_healthy"


def test_all_observability_services_have_profiles():
    """A-17: All observability services are in the 'observability' profile."""
    services = _services()
    for service_name in OBSERVABILITY_SERVICES:
        if service_name in services:
            service = services[service_name]
            assert "profiles" in service
            assert "observability" in service["profiles"]


def test_env_example_updated_for_a17():
    """A-17: .env.example contains the new environment variables."""
    env_example_path = REPO_ROOT / ".env.example"
    if not env_example_path.exists():
        pytest.skip(".env.example not found")

    content = env_example_path.read_text(encoding="utf-8")

    # Should contain the new A-17 variables
    new_vars = [
        "PROMETHEUS_URL",
        "PROMETHEUS_PORT",
        "CLICKHOUSE_OBS_DB",
        "AGENT_OBS_SAMPLER_AUDIT_ENABLED",
    ]

    for var in new_vars:
        assert var in content
