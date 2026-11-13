import pytest

from replaylab.engine import Engine, Fork, current_session, step
from replaylab.store import Store


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    return store, Engine(store)


def test_record_replay_restores_state_without_tool_calls(env):
    store, engine = env
    calls = []

    @step
    def increment(n=1):
        calls.append(n)
        current_session().state["n"] = n
        return n + 1

    def flow(data):
        return [increment(data), current_session().state["n"]]

    original = engine.run(flow, 4)
    replay = engine.run(flow, 4, mode="replay", source=original)
    assert calls == [4]
    assert store.get_run(replay)["output"] == [5, 4]
    assert store.steps(replay)[0]["origin"] == "replayed"
    assert store.steps(original)[0]["state_after"] == {"n": 4}


def test_record_does_not_silently_reuse_cache(env):
    _, engine = env
    calls = []

    @step
    def tool(x):
        calls.append(x)
        return x

    engine.run(tool, 1)
    engine.run(tool, 1)
    assert calls == [1, 1]


def test_prefix_mismatch_fails_without_calls(env):
    store, engine = env
    calls = []

    @step
    def tool(x):
        calls.append(x)
        return x

    original = engine.run(tool, 1)
    replay = engine.run(tool, 2, mode="replay", source=original)
    assert store.get_run(replay)["error"]["type"] == "ReplayDivergence"
    assert calls == [1]


def test_fork_tool_result_replays_prefix_and_reexecutes_suffix(env):
    store, engine = env
    calls = []

    @step
    def tool(x):
        calls.append(x)
        return x + 1

    def flow(data):
        a = tool(data)
        b = tool(a)
        return tool(b)

    original = engine.run(flow, 1)
    forked = engine.run(flow, 1, source=original, fork=Fork(2, {"tool_result": 10}))
    assert store.get_run(forked)["output"] == 11
    assert calls == [1, 2, 3, 10]
    assert [s["origin"] for s in store.steps(forked)] == ["replayed", "overridden", "executed"]


def test_failure_is_recorded_and_replayed(env):
    store, engine = env
    calls = []

    @step
    def broken(_):
        calls.append(1)
        raise ValueError("synthetic failure")

    original = engine.run(broken, None)
    replay = engine.run(broken, None, mode="replay", source=original)
    assert store.get_run(original)["status"] == "failed"
    assert store.steps(original)[0]["error"]["message"] == "synthetic failure"
    assert store.get_run(replay)["error"]["type"] == "RecordedFailure"
    assert calls == [1]
    assert store.cached(store.steps(original)[0]["key"]) is None


def test_shortened_replay_fails_closed(env):
    store, engine = env

    @step
    def tool(x):
        return x

    def flow(data):
        tool(data)
        return tool(data + 1)

    original = engine.run(flow, 1)

    # Same declared workflow, but control flow changed outside traced boundaries.
    def shorter(data):
        return tool(data)

    replay = engine.run(shorter, 1, mode="replay", source=original, name="same")
    assert store.get_run(replay)["status"] == "failed"


def test_tool_override_can_replace_state(env):
    store, engine = env

    @step
    def tool(x):
        current_session().state["value"] = x
        return x

    def flow(x):
        tool(x)
        return current_session().state

    original = engine.run(flow, 1)
    forked = engine.run(
        flow, 1, source=original, fork=Fork(1, {"tool_result": 2, "state_after": {"value": 2}})
    )
    assert store.get_run(forked)["output"] == {"value": 2}


def test_step_requires_session_and_rejects_async():
    @step
    def tool():
        return 1

    with pytest.raises(RuntimeError, match="Engine"):
        tool()

    with pytest.raises(TypeError, match="async"):

        @step
        async def asynchronous():
            return 1


def test_nested_steps_rejected(env):
    store, engine = env

    @step
    def inner():
        return 1

    @step
    def outer(_):
        return inner()

    run = engine.run(outer, None)
    assert store.get_run(run)["error"]["type"] == "RuntimeError"


@pytest.mark.parametrize(
    "edit",
    [
        {},
        {"unknown": 1},
        {"prompt": ""},
        {"params": {"model": "bad"}},
        {"tool_result": 1, "prompt": "bad"},
    ],
)
def test_invalid_fork_edits_rejected(edit):
    with pytest.raises(ValueError):
        Fork(1, edit)


def test_invalid_fork_position_rejected(env):
    _, engine = env
    with pytest.raises(ValueError):
        Fork(0, {"tool_result": 1})
    original = engine.run(lambda x: x, 1)
    with pytest.raises(ValueError, match="position"):
        engine.run(lambda x: x, 1, source=original, fork=Fork(1, {"tool_result": 2}))
