import shutil
import subprocess
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).resolve().parents[2]
CHAOS = LAB_ROOT / "chaos"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chaos_layout_exists() -> None:
    expected = [
        CHAOS / "README.md",
        CHAOS / "compose.chaos.yml",
        CHAOS / "k6" / "baseline.js",
        CHAOS / "k6" / "latency-experiment.js",
        CHAOS / "k6" / "orders-flow.js",
        CHAOS / "scripts" / "check-steady-state.ps1",
        CHAOS / "scripts" / "run-baseline.ps1",
        CHAOS / "scripts" / "run-latency-experiment.ps1",
        CHAOS / "scripts" / "apply-latency.ps1",
        CHAOS / "scripts" / "rollback-latency.ps1",
        CHAOS / "scripts" / "verify-recovery.ps1",
        CHAOS / "evidence" / ".gitkeep",
        LAB_ROOT / "services" / "service-b" / "Dockerfile.chaos",
    ]
    missing = [str(path) for path in expected if not path.exists()]
    assert missing == []


def test_chaos_dockerfile_matches_runtime_and_adds_only_iproute2() -> None:
    normal = read(LAB_ROOT / "services" / "service-b" / "Dockerfile")
    chaos = read(LAB_ROOT / "services" / "service-b" / "Dockerfile.chaos")
    for line in (
        "FROM python:3.12-slim",
        "USER app",
        'ENTRYPOINT ["python", "entrypoint.py"]',
        "COPY --chown=app:app app ./app",
        "COPY --chown=app:app alembic ./alembic",
    ):
        assert line in normal
        assert line in chaos
    assert "iproute2" in chaos
    assert "iproute2" not in normal
    assert "privileged" not in chaos.lower()


def test_overlay_limits_privileges_to_service_b() -> None:
    overlay = read(CHAOS / "compose.chaos.yml")
    normal = read(LAB_ROOT / "docker-compose.yml")
    assert "Dockerfile.chaos" in overlay
    assert "otel-multicloud-lab-service-b:chaos" in overlay
    assert "NET_ADMIN" in overlay
    assert "privileged" not in overlay.lower()
    assert "service-a" not in overlay
    assert "postgres" not in overlay
    assert "./services/service-b" in overlay
    assert "NET_ADMIN" not in normal
    assert "privileged:" not in normal


def test_k6_uses_the_real_order_flow_and_thresholds() -> None:
    flow = read(CHAOS / "k6" / "orders-flow.js")
    baseline = read(CHAOS / "k6" / "baseline.js")
    experiment = read(CHAOS / "k6" / "latency-experiment.js")
    assert "http://service-a:8080" in flow
    assert "/api/v1/orders" in flow
    assert "bench-customer" in flow
    assert "150000.5" in flow
    assert "'cop'" in flow
    assert "X-Request-ID" in flow
    assert "res.status === 201" in flow
    assert "rate<0.01" in flow
    assert "rate>=0.99" in flow
    assert "http_req_duration" in flow
    assert "http_req_failed" in flow
    assert "iterations" in flow
    assert "http_reqs" in flow
    assert "120s" in flow
    assert "orders-flow.js" in baseline
    assert "orders-flow.js" in experiment
    assert "'baseline'" in baseline
    assert "'latency'" in experiment
    assert "netem" not in experiment
    assert "qdisc" not in experiment


def test_scripts_cover_steady_state_latency_and_recovery() -> None:
    steady = read(CHAOS / "scripts" / "check-steady-state.ps1")
    baseline = read(CHAOS / "scripts" / "run-baseline.ps1")
    apply = read(CHAOS / "scripts" / "apply-latency.ps1")
    rollback = read(CHAOS / "scripts" / "rollback-latency.ps1")
    verify = read(CHAOS / "scripts" / "verify-recovery.ps1")
    common = read(CHAOS / "scripts" / "lab-common.ps1")
    assert "localhost:8081/health" in steady
    assert "localhost:8082/health" in steady
    assert "connected" in steady
    assert "netem" not in steady
    assert "check-steady-state.ps1" in baseline
    assert "baseline.js" in baseline
    assert "[int]$DelayMs = 200" in apply
    assert "[int]$JitterMs = 20" in apply
    assert "[int]$DurationSeconds = 120" in apply
    assert "try {" in apply
    assert "finally {" in apply
    assert "distribution" in apply
    assert "normal" in apply
    assert "Clear-ServiceBNetem" in apply
    assert "tc qdisc del dev eth0 root" in common
    assert "Clear-ServiceBNetem" in rollback
    assert "netem" in verify
    assert "30s" in verify
    assert "grafana/k6:2.3.0" in common
    assert "otel-collector" in steady


def test_gitignore_keeps_evidence_placeholder() -> None:
    gitignore = read(LAB_ROOT / ".gitignore")
    assert "chaos/evidence/*" in gitignore
    assert "!chaos/evidence/.gitkeep" in gitignore


def test_powershell_scripts_parse() -> None:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell no está instalado en este entorno")
    scripts = sorted((CHAOS / "scripts").glob("*.ps1"))
    assert scripts
    for script in scripts:
        command = (
            "$errors = $null; $tokens = $null; "
            "[void][System.Management.Automation.Language.Parser]::ParseFile("
            f"'{script}', [ref]$tokens, [ref]$errors); "
            "if ($errors -and $errors.Count -gt 0) { "
            "$errors | ForEach-Object { Write-Output $_.ToString() }; exit 1 }"
        )
        completed = subprocess.run(
            [executable, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
