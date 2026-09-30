"""Request and response models for the API (spec 02 §4), plus converters.

Converters here are pure: vault manifest entry → `VaultEntry`, a signature
string → name/args/ret, an interrupt value → its browser-safe payload.
"""

from __future__ import annotations

import ast
import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---- errors ---------------------------------------------------------------


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorOut(BaseModel):
    error: ErrorBody


# ---- sessions, messages, runs ---------------------------------------------------


class _FromRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SessionOut(_FromRow):
    id: uuid.UUID
    name: str
    number: int
    created_at: datetime
    updated_at: datetime


class MessageOut(_FromRow):
    id: uuid.UUID
    role: str
    html: str
    note: str | None
    chips: list[dict[str, Any]]
    run_id: uuid.UUID | None
    created_at: datetime


class RunSummaryOut(_FromRow):
    id: uuid.UUID
    n: int
    query: str
    status: str
    summary: str | None
    summary_gold: bool
    forged: list[str]
    used: list[str]
    failed: bool
    started_at: datetime
    finished_at: datetime | None


class PendingOut(BaseModel):
    kind: str
    payload: dict[str, Any]


class RunOut(RunSummaryOut):
    pending: PendingOut | None = None


class RunMarkOut(_FromRow):
    n: int
    query: str
    mark: str | None


class SessionSummaryOut(_FromRow):
    id: uuid.UUID
    name: str
    created_at: datetime
    run_count: int
    forged: list[str]
    used: list[str]
    runs: list[RunMarkOut]


class SessionDetailOut(BaseModel):
    session: SessionOut
    messages: list[MessageOut]
    runs: list[RunSummaryOut]


class StartRunOut(BaseModel):
    run: RunSummaryOut
    message: MessageOut


class RenameIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 80:
            raise ValueError("name must be 1 to 80 characters")
        return value


class MessageIn(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 4000:
            raise ValueError("text must be 1 to 4000 characters")
        return value


class ResumeIn(BaseModel):
    """`/resume` body. `value` is an API key: never logged or echoed (repr=False)."""

    decision: Literal["approve", "decline", "save", "skip"]
    value: str | None = Field(default=None, max_length=4096, repr=False)


# ---- vault ----------------------------------------------------------------------


class VaultEntry(BaseModel):
    name: str
    args: str
    ret: str
    signature: str
    description: str
    keywords: list[str]
    uses: int
    failures: int
    streak: int
    created_at: str | None
    last_used: str | None
    last_failure: str | None
    last_failed_at: str | None
    web: bool
    file: str


class VaultDetail(VaultEntry):
    source: str | None
    lines: int


class VaultListOut(BaseModel):
    count: int
    web_count: int
    failed_count: int
    tools: list[VaultEntry]


# ---- settings, health -------------------------------------------------------------


class KeyOut(BaseModel):
    name: str
    set: bool
    required: bool
    description: str


class SettingsOut(BaseModel):
    model: str
    ask_before_exec: bool
    forge_retries: int
    test_timeout_s: int
    llm_timeout_s: float
    prune_after: int
    keys: list[KeyOut]


class SettingsPatch(BaseModel):
    ask_before_exec: bool


class HealthOut(BaseModel):
    ok: bool
    db: bool
    fake_graph: bool
    version: str


# ---- converters ----------------------------------------------------------------------

_SIGNATURE = re.compile(r"^\s*[\w.]*\s*\((?P<args>.*)\)\s*(?:->\s*(?P<ret>.+?))?\s*$", re.S)
_WEB_MODULES = frozenset({"requests", "urllib", "httpx"})
_IMPORT_LINE = re.compile(r"^\s*import\s+(.+)$")
_FROM_LINE = re.compile(r"^\s*from\s+([\w.]+)\s+import\b")


def split_signature(signature: str) -> tuple[str, str]:
    """`"f(a: int, b: str) -> bool"` → `("a: int, b: str", "bool")`.

    Anything that doesn't look like a signature gives `("", "")`.
    """
    match = _SIGNATURE.match(signature or "")
    if match is None:
        return "", ""
    return match.group("args").strip(), (match.group("ret") or "").strip()


def imported_modules(source: str) -> set[str]:
    """Top-level names of every module `source` imports (`import a.b, c` → {"a", "c"}).

    Uses the AST; source that doesn't parse falls back to reading import lines.

    Args:
        source: Python source code.

    Returns:
        Top-level module names, excluding relative imports.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return _imported_modules_by_line(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def _imported_modules_by_line(source: str) -> set[str]:
    found: set[str] = set()
    for line in source.splitlines():
        for statement in line.split("#", 1)[0].split(";"):
            if match := _FROM_LINE.match(statement):
                found.add(match.group(1).split(".")[0])
            elif match := _IMPORT_LINE.match(statement):
                for part in match.group(1).split(","):
                    name = part.strip().split(" ")[0]
                    if name:
                        found.add(name.split(".")[0])
    return found


def is_web_source(source: str | None) -> bool:
    """True when a tool's source imports requests, urllib or httpx anywhere."""
    return bool(source) and not _WEB_MODULES.isdisjoint(imported_modules(source))


def vault_entry(entry: Mapping[str, Any], source: str | None) -> VaultEntry:
    """Turn a manifest entry (SkillEntry) into the API's VaultEntry."""
    signature = str(entry.get("signature") or "")
    args, ret = split_signature(signature)
    name = str(entry.get("name") or "")
    return VaultEntry(
        name=name,
        args=args,
        ret=ret,
        signature=signature,
        description=str(entry.get("description") or ""),
        keywords=[str(k) for k in entry.get("keywords") or []],
        uses=int(entry.get("usage_count") or 0),
        failures=int(entry.get("failure_count") or 0),
        streak=int(entry.get("consecutive_failures") or 0),
        created_at=entry.get("created_at"),
        last_used=entry.get("last_used"),
        last_failure=entry.get("last_failure_reason"),
        last_failed_at=entry.get("last_failed_at"),
        web=is_web_source(source),
        file=str(entry.get("file") or f"tools/{name}.py"),
    )


# Env var prefix → service name, for the key dialog's "This tool needs an X key".
_SERVICES = {
    "OPENWEATHERMAP": "OpenWeatherMap",
    "OPENWEATHER": "OpenWeatherMap",
    "OPENAI": "OpenAI",
    "OPENROUTER": "OpenRouter",
    "ANTHROPIC": "Anthropic",
    "TAVILY": "Tavily",
    "JINA": "Jina",
    "LANGSMITH": "LangSmith",
    "GITHUB": "GitHub",
    "NEWSAPI": "NewsAPI",
}


def service_name(env_var: str) -> str:
    """`OPENWEATHERMAP_API_KEY` → `OpenWeatherMap`; unknown names come back unchanged."""
    stem = re.sub(r"_(API_KEY|KEY|TOKEN|SECRET)$", "", env_var or "")
    return _SERVICES.get(stem, env_var)


InterruptKind = Literal["confirm_exec", "missing_api_key"]


def pending_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    """The browser-safe part of an interrupt value (overview §4.3).

    `confirm_exec` keeps `tool` and `preview` only: `args`/`kwargs` stay on
    the server so the browser never sends code back.
    """
    if value.get("type") == "confirm_exec":
        return {"tool": value.get("tool"), "preview": str(value.get("preview") or "")}
    env_var = str(value.get("env_var") or "")
    return {
        "env_var": env_var,
        "tool_name": value.get("tool_name"),
        "service": service_name(env_var),
    }
