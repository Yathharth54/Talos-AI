"""The talos-web entry point."""

from __future__ import annotations

import tomllib

from talos.config import settings
from talos.web import __main__ as web_main


def test_talos_web_runs_one_local_worker(monkeypatch):
    calls = {}
    monkeypatch.setattr(web_main.uvicorn, "run", lambda *a, **k: calls.update(args=a, kw=k))
    web_main.main()
    assert calls["args"] == ("talos.web.app:create_app",)
    assert calls["kw"]["factory"] is True
    assert calls["kw"]["workers"] == 1
    assert (calls["kw"]["host"], calls["kw"]["port"]) == (settings.WEB_HOST, settings.WEB_PORT)


def test_talos_web_script_is_declared():
    with open(settings.PROJECT_ROOT / "pyproject.toml", "rb") as f:
        scripts = tomllib.load(f)["project"]["scripts"]
    assert scripts["talos-web"] == "talos.web.__main__:main"
