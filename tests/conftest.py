"""Test-wide setup. Runs before any test imports.

Disables LangSmith tracing during tests so we don't spam the LangSmith
quota with mock-LLM traces (which are noisy and useless). Live tests
that need tracing can re-enable it explicitly.
"""

from __future__ import annotations

import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGCHAIN_TRACING_V2", None)
