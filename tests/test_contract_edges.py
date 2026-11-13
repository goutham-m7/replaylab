import pytest

from replaylab import Engine, Fork, Store, step
from replaylab.providers import ChatClient, MockProvider, OpenAIProvider


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "unknown"},
        {"mode": "replay"},
        {"source": "missing"},
        {"fork": Fork(1, {"tool_result": 1})},
    ],
)
def test_invalid_execution_options_do_not_create_runs(tmp_path, kwargs):
    store = Store(tmp_path / "trace.sqlite")
    with pytest.raises(ValueError):
        Engine(store).run(lambda x: x, None, **kwargs)
    assert store.list_runs() == []


def test_tool_default_arguments_have_same_hash_as_explicit_values(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)

    @step
    def tool(x=3):
        return x

    a = engine.run(lambda _: tool(), None)
    b = engine.run(lambda _: tool(x=3), None, source=a, mode="replay")
    assert store.get_run(b)["output"] == 3
    assert store.steps(a)[0]["key"] == store.steps(b)[0]["key"]


def test_replay_missing_suffix_never_executes_new_boundary(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)
    calls = []

    @step
    def tool(value):
        calls.append(value)
        return value

    original = engine.run(lambda value: tool(value), 1)

    def extended(value):
        tool(value)
        return tool(value + 1)

    replay = engine.run(extended, 1, source=original, mode="replay")
    assert store.get_run(replay)["error"]["type"] == "ReplayDivergence"
    assert calls == [1]


@pytest.mark.parametrize(
    "model,messages",
    [
        ("", [{"role": "user", "content": "x"}]),
        ("mock", []),
        ("mock", [{"role": "user", "content": []}]),
    ],
)
def test_invalid_chat_requests_are_rejected_without_provider_calls(tmp_path, model, messages):
    store = Store(tmp_path / "trace.sqlite")
    provider = MockProvider()
    run = Engine(store).run(
        lambda _: ChatClient(provider).create(model=model, messages=messages), None
    )
    assert store.get_run(run)["status"] == "failed"
    assert provider.calls == 0


def test_empty_provider_key_rejected():
    with pytest.raises(ValueError, match="key"):
        OpenAIProvider("https://example.test/v1", " ")


@pytest.mark.parametrize(
    "edit", [{"params": []}, {"state_after": {}}, {"tool_result": 1, "state_after": []}, []]
)
def test_fork_edit_contract_rejects_wrong_types(edit):
    with pytest.raises(ValueError):
        Fork(1, edit)
