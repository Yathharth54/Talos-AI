"""Settings: the ask-before-exec switch and which keys are set (spec 02 §4, §7)."""

from __future__ import annotations

import os

from dotenv import dotenv_values
from fastapi import APIRouter, Depends

from talos.agents import hitl
from talos.config import settings
from talos.vault.manager import _AUTO_PRUNE_THRESHOLD
from talos.web import copy
from talos.web.deps import ASK_BEFORE_EXEC, get_store
from talos.web.schemas import KeyOut, SettingsOut, SettingsPatch
from talos.web.store import Store

router = APIRouter()

KNOWN_KEYS = (
    ("OPENROUTER_API_KEY", True),
    ("TAVILY_API_KEY", True),
    ("JINA_API_KEY", False),
    ("LANGSMITH_API_KEY", False),
)


def _keys() -> list[KeyOut]:
    """Known keys, then every other *_API_KEY in .env. Never the values."""
    try:
        saved = dotenv_values(hitl.DOTENV_PATH) if hitl.DOTENV_PATH.exists() else {}
    except OSError:
        saved = {}
    known = {name for name, _ in KNOWN_KEYS}
    keys = [
        KeyOut(
            name=name,
            set=bool(os.environ.get(name) or saved.get(name)),
            required=required,
            description=copy.KEY_DESCRIPTIONS[name],
        )
        for name, required in KNOWN_KEYS
    ]
    for name in sorted(n for n in saved if n.endswith("_API_KEY") and n not in known):
        keys.append(
            KeyOut(
                name=name,
                set=bool(saved.get(name) or os.environ.get(name)),
                required=False,
                description=copy.KEY_SAVED_BY_HUMAN_CHECK,
            )
        )
    return keys


def current_settings() -> SettingsOut:
    """The Settings page: model, limits, the "Ask before running code" switch and key rows.

    Returns:
        The settings as this process applies them now. Key values are never included.
    """
    return SettingsOut(
        model=settings.TALOS_MODEL,
        ask_before_exec=not settings.auto_approve_exec(),
        forge_retries=settings.FORGE_MAX_RETRIES,
        test_timeout_s=settings.SUBPROCESS_TIMEOUT,
        llm_timeout_s=settings.LLM_TIMEOUT,
        prune_after=_AUTO_PRUNE_THRESHOLD,
        keys=_keys(),
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings() -> SettingsOut:
    """The current settings (see `current_settings`)."""
    return current_settings()


@router.patch("/settings", response_model=SettingsOut)
async def patch_settings(body: SettingsPatch, store: Store = Depends(get_store)) -> SettingsOut:
    """Store the switch and apply it to this process at once."""
    await store.set_setting(ASK_BEFORE_EXEC, body.ask_before_exec)
    settings.set_auto_approve_override(not body.ask_before_exec)
    return current_settings()
