import httpx
import pytest

from replaylab import Engine, Fork, Store, current_session, step
from replaylab.providers import OpenAIProvider


def test_non_object_state_is_a_recorded_failure_not_a_cache_entry(tmp_path):
    store = Store(tmp_path / "trace.sqlite")

    @step
    def invalid(_):
        current_session().state = []
        return "invalid"

    run = Engine(store).run(invalid, None)
    assert store.get_run(run)["status"] == "failed"
    trace = store.steps(run)[0]
    assert trace["error"]["type"] == "TypeError"
    assert trace["state_after"] == {}
    assert store.cached(trace["key"]) is None


def test_non_json_state_still_leaves_useful_failure_trace(tmp_path):
    store = Store(tmp_path / "trace.sqlite")

    @step
    def invalid(_):
        current_session().state["bad"] = object()
        return "value"

    run = Engine(store).run(invalid, None)
    assert store.get_run(run)["status"] == "failed"
    assert store.steps(run)[0]["state_after"] == {}


def test_running_source_rejected_before_creating_child(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    source = store.create_run("flow", {}, "record", None, None)
    with pytest.raises(ValueError, match="running"):
        Engine(store).run(lambda x: x, {}, mode="replay", source=source)
    assert len(store.list_runs()) == 1


def test_in_memory_database_rejected_explicitly():
    with pytest.raises(ValueError, match="file"):
        Store(":memory:")


@pytest.mark.parametrize(
    "body", [{"choices": [1]}, {"choices": [None]}, {"choices": [{"message": "bad"}]}]
)
def test_malformed_provider_choice_rejected_as_contract_error(body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as http:
        with pytest.raises(ValueError, match="completion"):
            OpenAIProvider("http://localhost/v1", "key", http=http).complete({})


def test_fork_snapshot_is_detached_from_edit_mutations(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)

    @step
    def tool(_):
        return "old"

    changes = {"tool_result": {"value": 1}}
    edit = Fork(1, changes)
    changes["tool_result"]["value"] = 999
    original = engine.run(tool, None)
    forked = engine.run(tool, None, source=original, fork=edit)
    assert store.get_run(forked)["output"] == {"value": 1}
