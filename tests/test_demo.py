from replaylab.demo import FIXED_PROMPT, research_workflow, run_demo
from replaylab.diff import compare
from replaylab.engine import Engine, Fork
from replaylab.providers import MockProvider
from replaylab.store import Store


def test_demo_fails_at_four_then_repairs_without_repeating_prefix(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    result = run_demo(store)
    original = store.get_run(result["original"])
    forked = store.get_run(result["fork"])
    assert original["status"] == "failed"
    assert len(store.steps(original["id"])) == 4
    assert store.steps(original["id"])[-1]["error"] is not None
    assert forked["status"] == "completed"
    assert "[S1]" in forked["output"]["answer"]
    assert result["prefix_replayed"] == 3
    assert result["original_provider_calls"] == 3
    assert result["fork_provider_calls"] == 1
    assert [r["status"] for r in result["diff"]["steps"]] == [
        "unchanged",
        "unchanged",
        "unchanged",
        "changed",
        "added",
    ]


def test_repeated_identical_fork_reuses_suffix_cache(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)
    provider = MockProvider()
    flow = research_workflow(provider)
    original = engine.run(flow, {"question": "offline storage?"})
    first = engine.run(
        flow,
        {"question": "offline storage?"},
        source=original,
        fork=Fork(4, {"prompt": FIXED_PROMPT}),
    )
    count = provider.calls
    second = engine.run(
        flow,
        {"question": "offline storage?"},
        source=original,
        fork=Fork(4, {"prompt": FIXED_PROMPT}),
    )
    assert provider.calls == count
    assert store.get_run(first)["output"] == store.get_run(second)["output"]
    assert store.steps(second)[3]["origin"] == "cached"
    assert compare(store, first, second)["changed"] == 0
