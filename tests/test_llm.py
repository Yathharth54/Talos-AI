"""LLM factory — structured-output retry wrapper.

Non-OpenAI models sometimes answer in prose instead of calling the schema
tool; LangChain's function_calling parser then returns None. The wrapper
retries once with a nudge and raises a clear error if it's still None.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from talos.config import llm as llm_mod
from talos.config.llm import StructuredOutputError


class _Out(BaseModel):
    value: int


class _Seq:
    """Stand-in for chat_model.with_structured_output(...): returns a canned
    sequence of results (or raises when an item is an Exception)."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _patched(monkeypatch, inner: _Seq):
    class _Chat:
        def with_structured_output(self, schema, method=None):
            return inner

    monkeypatch.setattr(llm_mod, "make_chat_model", lambda temperature: _Chat())
    return llm_mod.make_structured_model(_Out, temperature=0.0)


def test_returns_first_result_when_valid(monkeypatch):
    inner = _Seq(_Out(value=1))
    assert _patched(monkeypatch, inner).invoke(["m"]) == _Out(value=1)
    assert len(inner.calls) == 1


def test_retries_once_with_nudge_when_none(monkeypatch):
    inner = _Seq(None, _Out(value=2))
    assert _patched(monkeypatch, inner).invoke(["m"]) == _Out(value=2)
    assert len(inner.calls) == 2
    nudge = inner.calls[1][-1].content
    assert "_Out" in nudge


def test_retries_once_when_parser_raises(monkeypatch):
    inner = _Seq(ValueError("bad tool args"), _Out(value=3))
    assert _patched(monkeypatch, inner).invoke(["m"]) == _Out(value=3)


def test_raises_structured_output_error_after_two_failures(monkeypatch):
    inner = _Seq(None, None)
    with pytest.raises(StructuredOutputError, match="_Out"):
        _patched(monkeypatch, inner).invoke(["m"])
