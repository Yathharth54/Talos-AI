"""web_read primitive — Jina Reader fetches any URL as clean markdown.

Concept:
- Jina's `r.jina.ai/{url}` endpoint scrapes + cleans + markdown-ifies any
  public URL. Way friendlier than raw HTML for an LLM to consume.
- Auth: free without a key (rate-limited), or `Authorization: Bearer ...`
  with the free Jina API key for higher quotas.
- We use plain `requests` — no LangChain document loader needed. Loaders
  return `Document` objects with metadata, useful for RAG pipelines but
  overkill here.
"""

from __future__ import annotations

import requests

from talos.config import settings

_JINA_BASE = "https://r.jina.ai/"


def web_read(url: str, timeout: int = 30) -> str:
    """Fetch any public URL via Jina Reader and return clean markdown.

    Args:
        url: full http(s) URL to fetch.
        timeout: HTTP timeout in seconds.

    Returns:
        Markdown string (Jina always returns text, even for HTML pages).

    Raises:
        requests.HTTPError on non-2xx response.
        ValueError on malformed url input.
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"web_read requires a full http(s) URL, got: {url!r}")

    headers = {"Accept": "text/markdown"}
    if settings.JINA_API_KEY:
        headers["Authorization"] = f"Bearer {settings.JINA_API_KEY}"

    response = requests.get(_JINA_BASE + url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text
