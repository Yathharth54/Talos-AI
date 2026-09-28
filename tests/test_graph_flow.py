"""Phase 7 graph-shape tests.

These verify the production graph compiles and exposes the expected
nodes. End-to-end behaviour lives in tests/test_orchestrator.py.
"""

from __future__ import annotations

from talos.graph import app, build_graph


def test_graph_compiles():
    compiled = build_graph().compile()
    assert compiled is not None


def test_graph_exposes_expected_nodes():
    """Sanity check on the topology: all the production nodes exist."""
    nodes = set(app.get_graph().nodes.keys())
    expected = {
        "orchestrator_in",
        "planner",
        "_dispatch",
        "forge_subgraph",
        "learn",
        "executor",
        "advance",
        "orchestrator_out",
    }
    assert expected.issubset(nodes), f"missing: {expected - nodes}"


def test_checkpointer_saves_values_msgpack_cannot():
    """Tool outputs can be anything: big ints (2**100), sets, custom objects.
    The checkpointer must persist them instead of crashing the query."""
    from talos.graph import checkpointer, make_checkpointer

    value = {"big": 2**100, "set": {1, 2}}
    for saver in (checkpointer, make_checkpointer()):
        assert saver.serde.loads_typed(saver.serde.dumps_typed(value)) == value
