"""vault_list primitive — lets Talos answer questions about its own skills.

Read-only view of the Skill Vault manifest ("what tools do you have?",
"how many times has X been used?"). No file contents, just metadata.
"""

from __future__ import annotations

from talos.vault.manager import SkillManager


def _get_skill_manager() -> SkillManager:
    """SkillManager factory; test seam."""
    return SkillManager()


def vault_list() -> list[dict]:
    """List every forged tool in the vault.

    Returns:
        One dict per tool with name, description, signature and usage_count.

    Example:
        >>> vault_list()
        [{'name': 'slugify', 'description': '...', 'signature': '...', 'usage_count': 3}]
    """
    return [
        {
            "name": e.get("name"),
            "description": e.get("description"),
            "signature": e.get("signature"),
            "usage_count": e.get("usage_count", 0),
        }
        for e in _get_skill_manager().all()
    ]
