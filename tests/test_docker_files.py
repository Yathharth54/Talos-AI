"""Safety settings in the Docker and compose files (spec 03 §3–§5).

These are plain text/YAML checks, so they run in the unit suite with no
Docker. They pin the settings a later edit could silently weaken.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent

# The test image holds neither the Docker files nor the Makefile (they are
# build inputs, not runtime files), so the module only runs from a checkout.
pytestmark = pytest.mark.skipif(
    not (ROOT / "compose.yml").exists(), reason="Docker files not in this tree"
)


def _compose(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_app_is_published_on_localhost_only():
    app = _compose("compose.yml")["services"]["app"]
    assert app["ports"] == ["127.0.0.1:8000:8000"]


def test_db_publishes_no_port_except_in_the_dev_override():
    assert "ports" not in _compose("compose.yml")["services"]["db"]
    assert _compose("compose.dev.yml")["services"]["db"]["ports"] == ["127.0.0.1:5432:5432"]


def test_app_container_is_locked_down():
    app = _compose("compose.yml")["services"]["app"]
    assert app["read_only"] is True
    assert app["tmpfs"] == ["/tmp"]
    assert app["cap_drop"] == ["ALL"]
    assert app["security_opt"] == ["no-new-privileges:true"]
    assert app["mem_limit"] == "2g"
    assert app["pids_limit"] == 256


def test_containers_run_an_init_process_to_reap_killed_sandbox_children():
    assert _compose("compose.yml")["services"]["app"]["init"] is True
    assert _compose("compose.test.yml")["services"]["tests"]["init"] is True


def test_container_paths_are_pinned_over_the_env_file():
    env = _compose("compose.yml")["services"]["app"]["environment"]
    assert env["TALOS_VAULT_DIR"] == "/data/vault"
    assert env["TALOS_WORKSPACE_DIR"] == "/data/workspace"
    assert env["TALOS_DOTENV_PATH"] == "/data/.env"
    assert env["TALOS_WEB_PORT"] == "8000"
    assert env["TALOS_CHECKPOINTER"] == "postgres"


def test_cli_and_web_app_share_the_vault():
    volumes = _compose("compose.yml")["services"]["app"]["volumes"]
    assert "./talos/vault:/data/vault" in volumes
    assert "./.env:/data/.env" in volumes


def test_integration_tests_never_use_the_default_project():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "docker compose -p talos-test -f compose.yml -f compose.test.yml" in makefile
    tests = _compose("compose.test.yml")["services"]["tests"]
    assert tests["build"] == {"context": ".", "target": "test"}
    assert tests["environment"]["TALOS_FAKE_GRAPH"] == "1"


def test_dockerignore_keeps_secrets_and_local_state_out():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for pattern in (
        ".env",
        ".git",
        ".venv",
        "workspace/",
        "talos/vault/tools/*.py",
        "talos/vault/manifest.json",
        "**/node_modules",
    ):
        assert pattern in ignored


def test_image_runs_as_uid_1000_with_a_healthcheck():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "useradd --uid 1000" in dockerfile
    assert "\nUSER talos\n" in dockerfile
    assert "/api/health" in dockerfile
    assert 'ENTRYPOINT ["/app/docker/entrypoint.sh"]' in dockerfile
