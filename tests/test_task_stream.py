"""The streaming plan must produce the same plan, just sooner.

`/generate` returns after ~328 Aito calls — sixteen seconds of blank
screen, and in production a 502 once its timing header outgrew nginx's
buffer. Streaming fixes the wait without asking Aito to do less, which
matters because the fan-out IS the demonstration.

These tests use a stub client: the point is the event protocol and the
equivalence with the non-streaming path, not Aito's answers.
"""

import pytest

from src import task_service


class _StubClient:
    """Answers the two shapes `generate_plan` asks for, deterministically."""

    api_version = "v2"

    def search(self, table, where=None, limit=None, **kw):
        if table == "tasks":
            return {"hits": [
                {"phase": "site-prep", "task_name": "Site survey"},
                {"phase": "site-prep", "task_name": "Fencing"},
                {"phase": "finishing", "task_name": "Painting"},
            ] * 5}
        return {"hits": [], "total": 0}

    def predict(self, table, where, field, **kw):
        return {"hits": [{"$p": 0.5, "feature": "X", "$why": {}}]}


def _events(**kw):
    return list(task_service.stream_plan(
        _StubClient(), project_type="construction",
        region="Helsinki", season="summer", **kw))


def test_meta_arrives_before_any_task():
    """The view draws its phase skeleton from `meta`. If it were not
    first there would be nothing to show during the slowest part."""
    events = _events()
    assert events[0]["type"] == "meta"
    assert events[0]["phases"]
    assert events[0]["expected_tasks"] > 0
    kinds = [e["type"] for e in events]
    assert kinds.index("meta") < kinds.index("task")


def test_the_stream_ends_with_done_and_totals():
    events = _events()
    assert events[-1]["type"] == "done"
    for key in ("purchases", "total_planned_days",
                "total_planned_cost_eur", "total_purchases_eur"):
        assert key in events[-1], key


def test_every_expected_task_is_emitted_exactly_once():
    events = _events()
    tasks = [e for e in events if e["type"] == "task"]
    assert len(tasks) == events[0]["expected_tasks"]
    pairs = {(e["task"]["phase"], e["task"]["task_name"]) for e in tasks}
    assert len(pairs) == len(tasks), "a task was emitted twice"
    assert [e["index"] for e in tasks] == list(range(1, len(tasks) + 1))


def test_the_running_call_tally_never_goes_backwards():
    """It drives the latency pill, which cannot read a response header
    once the body has begun."""
    tallies = [e["calls_total"] for e in _events() if e["type"] == "task"]
    assert tallies == sorted(tallies)
    assert all(len(e["calls_recent"]) <= 12
               for e in _events() if e["type"] == "task")


def test_streaming_and_blocking_agree():
    """The two paths share a scaffold precisely so they cannot drift."""
    blocking = task_service.generate_plan(
        _StubClient(), project_type="construction",
        region="Helsinki", season="summer").to_dict()
    events = _events()
    streamed = [e["task"] for e in events if e["type"] == "task"]

    assert len(streamed) == len(blocking["tasks"])
    assert ({(t["phase"], t["task_name"]) for t in streamed}
            == {(t["phase"], t["task_name"]) for t in blocking["tasks"]})
    assert events[-1]["total_planned_days"] == blocking["total_planned_days"]
    assert events[-1]["purchases"] == blocking["purchases"]


def test_a_history_free_project_type_still_terminates():
    """No history means no plan, and the stream still has to close
    cleanly — a view waiting on `done` would otherwise hang."""
    class _Empty(_StubClient):
        def search(self, *a, **kw):
            return {"hits": [], "total": 0}

    events = list(task_service.stream_plan(
        _Empty(), project_type="nope", region="Helsinki", season="summer"))
    assert [e["type"] for e in events] == ["meta", "done"]
