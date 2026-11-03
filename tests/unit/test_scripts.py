"""Unit tests for the start/stop scripts (no infra needed, static checks).

Locks in the full-stack behaviour: stop must tear down every compose
profile (parity with `make stack-down`), start must offer --stack /
auto-Docker / port fallback, and the shell scripts must parse.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
SCRIPTS = REPO_ROOT / "scripts"

START_SH = SCRIPTS / "start.sh"
START_PS1 = SCRIPTS / "start.ps1"
STOP_SH = SCRIPTS / "stop.sh"
STOP_PS1 = SCRIPTS / "stop.ps1"


def _read(path: Path) -> str:
    # UTF-8 with BOM for .ps1 (PowerShell 5.1 needs it), plain UTF-8 for .sh.
    return path.read_text(encoding="utf-8-sig")


def test_scripts_exist():
    for path in (START_SH, START_PS1, STOP_SH, STOP_PS1):
        assert path.is_file(), f"missing script: {path}"


# --- stop: full compose stack teardown --------------------------------------


def test_stop_scripts_tear_down_all_profiles():
    """`docker compose down` alone skips profile services — stop must not."""
    for path in (STOP_SH, STOP_PS1):
        text = _read(path)
        assert "--profile app" in text, f"{path.name}: missing app profile"
        assert "--profile observability" in text, (
            f"{path.name}: missing observability profile"
        )
        # The down call itself must carry the flags (not just a comment).
        assert "docker compose --profile app --profile observability down" in text, (
            f"{path.name}: compose down must enable every profile"
        )


def test_stop_scripts_clean_stale_start_locks():
    for path in (STOP_SH, STOP_PS1):
        text = _read(path)
        assert "start.sh.lock" in text, f"{path.name}: must clean start.sh.lock"
        assert "start.ps1.lock" in text, f"{path.name}: must clean start.ps1.lock"


def test_stop_scripts_run_compose_down_before_port_sweep():
    """Docker listeners can only be freed by `down` — sweep must come after."""
    for path in (STOP_SH, STOP_PS1):
        text = _read(path)
        down_at = text.find("observability down")
        # Port sweep marker: first occurrence of the listener-skip logic.
        sweep_at = text.find("остаточный слушатель")
        assert down_at != -1 and sweep_at != -1, f"{path.name}: markers missing"
        assert down_at < sweep_at, (
            f"{path.name}: compose down must run before the port sweep"
        )


# --- start: stack mode, docker auto-start, port fallback --------------------


def test_start_scripts_offer_stack_mode():
    assert "--stack" in _read(START_SH), "start.sh missing --stack flag"
    ps1 = _read(START_PS1)
    assert "[switch]$Stack" in ps1, "start.ps1 missing -Stack switch"
    for path in (START_SH, START_PS1):
        text = _read(path)
        assert "observability" in text, f"{path.name}: stack mode must know the profile"
        assert "up -d --build" in text, f"{path.name}: stack mode must build images"


def test_start_scripts_auto_start_docker_daemon():
    for path in (START_SH, START_PS1):
        text = _read(path)
        assert "no-docker-start" in text or "NoDockerStart" in text, (
            f"{path.name}: missing opt-out for docker auto-start"
        )
    assert "Docker Desktop" in _read(START_PS1), "start.ps1 must launch Docker Desktop"
    assert "systemctl start docker" in _read(START_SH), (
        "start.sh must try systemctl on Linux"
    )


def test_start_scripts_fall_back_on_busy_db_ports():
    for path in (START_SH, START_PS1):
        text = _read(path)
        assert "занят посторонним процессом" in text, (
            f"{path.name}: explicit busy port must fail fast with owner"
        )
        assert "подбираю свободный" in text, (
            f"{path.name}: implicit busy port must fall back to a free one"
        )
        # runtime.env must be written before `compose up` so a failed up
        # still remembers the chosen ports.
        if path == START_SH:
            write_at = text.find('>"$RUNTIME_FILE"')
            up_at = text.find('step "docker compose up -d postgres redis"')
        else:
            write_at = text.find("Set-Content -LiteralPath $RuntimeFile")
            up_at = text.find('Write-Step "docker compose up -d postgres redis"')
        assert write_at != -1 and up_at != -1, f"{path.name}: markers missing"
        assert write_at < up_at, (
            f"{path.name}: runtime.env must be written before compose up"
        )


# --- syntax -----------------------------------------------------------------


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")
@pytest.mark.parametrize("script", ["start.sh", "stop.sh"])
def test_shell_scripts_parse(script: str):
    # Relative path + cwd: Git Bash rejects Windows absolute paths (C:\...).
    result = subprocess.run(  # noqa: S603
        ["bash", "-n", f"scripts/{script}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("powershell") is None, reason="powershell not on PATH")
@pytest.mark.parametrize("script", ["start.ps1", "stop.ps1"])
def test_powershell_scripts_parse(script: str):
    """PSParser::ParseFile — syntax only, the script body never runs."""
    command = (
        "$e=$null;$t=$null;"
        f"[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{(SCRIPTS / script).as_posix()}',[ref]$t,[ref]$e);"
        "if($e.Count){$e|%{$_.Message};exit 1}"
    )
    result = subprocess.run(  # noqa: S603
        ["powershell", "-NoProfile", "-Command", command],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
