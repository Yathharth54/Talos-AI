"""The vault: list, detail with source, remove (spec 02 §4 Vault)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response

from talos.vault.manager import SkillManager
from talos.web.deps import get_vault, not_found
from talos.web.schemas import VaultDetail, VaultListOut, vault_entry

router = APIRouter()


def _source(vault: SkillManager, entry: dict[str, Any]) -> str | None:
    path = vault.vault_dir / str(entry.get("file") or f"tools/{entry.get('name')}.py")
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


@router.get("/vault", response_model=VaultListOut)
async def list_vault(vault: SkillManager = Depends(get_vault)) -> VaultListOut:
    """Every tool, most recently used (or created) first."""
    tools = [vault_entry(e, _source(vault, e)) for e in vault.all()]
    tools.sort(key=lambda t: t.last_used or t.created_at or "", reverse=True)
    return VaultListOut(
        count=len(tools),
        web_count=sum(t.web for t in tools),
        failed_count=sum(t.failures > 0 for t in tools),
        tools=tools,
    )


@router.get("/vault/{name}", response_model=VaultDetail)
async def get_tool(name: str, vault: SkillManager = Depends(get_vault)) -> VaultDetail:
    entry = vault.get(name)
    if entry is None:
        raise not_found("Tool")
    source = _source(vault, entry)
    base = vault_entry(entry, source).model_dump()
    return VaultDetail(**base, source=source, lines=len(source.split("\n")) if source else 0)


@router.delete("/vault/{name}", status_code=204)
async def remove_tool(name: str, vault: SkillManager = Depends(get_vault)) -> Response:
    """Take a tool out of the manifest. Its .py file stays on disk."""
    if not vault.remove(name):
        raise not_found("Tool")
    return Response(status_code=204)
