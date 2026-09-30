"""Vault and Settings endpoints (spec 02 §4 Vault, Settings; §7)."""

from __future__ import annotations

from talos.config import settings
from tests.web.conftest import wait_for_status

WEB_TOOL = "import requests\n\n\ndef fetch_x() -> str:\n    return requests.get('https://x').text\n"


def seed(vault) -> None:
    vault.register(
        {
            "name": "slugify",
            "function": "slugify",
            "signature": "slugify(title: str) -> str",
            "description": "Slug it.",
            "keywords": ["slug"],
            "created_at": "2026-09-28T14:58:00+00:00",
            "last_used": "2026-09-28T15:30:00+00:00",
            "usage_count": 3,
        },
        "def slugify(title: str) -> str:\n    return title.lower()\n",
    )
    vault.register(
        {
            "name": "fetch_x",
            "function": "fetch_x",
            "signature": "fetch_x() -> str",
            "created_at": "2026-09-28T15:00:00+00:00",
        },
        WEB_TOOL,
    )
    vault.record_failure("fetch_x", reason="HTTPError: 500")


async def test_vault_list_counts_and_order(client, services):
    seed(services.vault)
    body = (await client.get("/api/vault")).json()
    assert (body["count"], body["web_count"], body["failed_count"]) == (2, 1, 1)
    assert [t["name"] for t in body["tools"]] == ["slugify", "fetch_x"]  # last used first
    slug = body["tools"][0]
    assert (slug["args"], slug["ret"], slug["uses"], slug["web"]) == ("title: str", "str", 3, False)
    fetch = body["tools"][1]
    assert (fetch["args"], fetch["failures"], fetch["streak"], fetch["web"]) == ("", 1, 1, True)
    assert fetch["last_failure"] == "HTTPError: 500"


async def test_vault_detail_has_the_source_and_404s(client, services):
    seed(services.vault)
    detail = (await client.get("/api/vault/slugify")).json()
    assert detail["source"].startswith("def slugify")
    assert detail["lines"] == 2  # two lines of code; the trailing newline ends the last one
    assert detail["file"] == "tools/slugify.py"
    response = await client.get("/api/vault/nope")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


async def test_vault_delete_keeps_the_file(client, services):
    seed(services.vault)
    response = await client.delete("/api/vault/slugify")
    assert response.status_code == 204
    assert services.vault.get("slugify") is None
    assert (services.vault.tools_dir / "slugify.py").exists()
    assert (await client.get("/api/vault/slugify")).status_code == 404
    assert (await client.delete("/api/vault/slugify")).status_code == 404


async def test_fake_forge_shows_up_in_the_vault(client):
    sid = (await client.post("/api/sessions")).json()["id"]
    text = 'Encrypt "TALOS AGENT" with a Caesar cipher, shift of 7.'
    run = (await client.post(f"/api/sessions/{sid}/messages", json={"text": text})).json()["run"]
    await wait_for_status(client, run["id"], "done")
    detail = (await client.get("/api/vault/caesar_cipher")).json()
    assert detail["args"] == "text: str, shift: int, mode: str"
    assert detail["lines"] == 63  # the demo's 63 lines, as the reader counts them
    assert detail["uses"] == 1


async def test_settings_shape_and_key_rows(client, dotenv, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    dotenv.write_text("OPENWEATHERMAP_API_KEY=owm-secret\nOTHER=1\n", encoding="utf-8")
    body = (await client.get("/api/settings")).json()
    assert body["model"] == settings.TALOS_MODEL
    assert body["ask_before_exec"] is True
    assert (body["forge_retries"], body["test_timeout_s"]) == (
        settings.FORGE_MAX_RETRIES,
        settings.SUBPROCESS_TIMEOUT,
    )
    assert body["llm_timeout_s"] == settings.LLM_TIMEOUT
    assert body["prune_after"] == 2
    keys = {k["name"]: k for k in body["keys"]}
    assert list(keys)[:4] == [
        "OPENROUTER_API_KEY",
        "TAVILY_API_KEY",
        "JINA_API_KEY",
        "LANGSMITH_API_KEY",
    ]
    assert keys["OPENROUTER_API_KEY"] == {
        "name": "OPENROUTER_API_KEY",
        "set": True,
        "required": True,
        "description": "Required. Every model call goes through OpenRouter.",
    }
    assert keys["TAVILY_API_KEY"]["set"] is False
    assert keys["OPENWEATHERMAP_API_KEY"] == {
        "name": "OPENWEATHERMAP_API_KEY",
        "set": True,
        "required": False,
        "description": "Saved by Human check this session.",
    }
    assert "OTHER" not in keys
    text = (await client.get("/api/settings")).text
    assert "sk-or-secret" not in text and "owm-secret" not in text


async def test_patch_ask_before_exec_applies_and_persists(client, services):
    try:
        body = (await client.patch("/api/settings", json={"ask_before_exec": False})).json()
        assert body["ask_before_exec"] is False
        assert settings.auto_approve_exec() is True
        assert await services.store.get_setting("ask_before_exec") is False

        sid = (await client.post("/api/sessions")).json()["id"]
        text = "Run this Python code: print(2 + 2)"
        sent = await client.post(f"/api/sessions/{sid}/messages", json={"text": text})
        run = sent.json()["run"]
        done = await wait_for_status(client, run["id"], "done")  # no approval pause
        assert done["summary"] == "Built-in"

        assert (
            await client.patch("/api/settings", json={"ask_before_exec": "nope"})
        ).status_code == 422
        await client.patch("/api/settings", json={"ask_before_exec": True})
        assert settings.auto_approve_exec() is False
    finally:
        settings.set_auto_approve_override(None)  # never leak into other tests
