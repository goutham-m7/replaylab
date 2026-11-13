from replaylab import Engine, Fork, Store, current_session, step
from replaylab.providers import ChatClient, MockProvider


def test_forked_prompt_can_be_replayed_without_provider_calls(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)
    provider = MockProvider()
    client = ChatClient(provider)

    def flow(text):
        return client.create(model="mock", messages=[{"role": "user", "content": text}])

    original = engine.run(flow, "original")
    forked = engine.run(flow, "original", source=original, fork=Fork(1, {"prompt": "edited"}))
    calls = provider.calls
    replay = engine.run(flow, "original", source=forked, mode="replay")
    assert store.get_run(replay)["status"] == "completed"
    assert store.get_run(replay)["output"] == store.get_run(forked)["output"]
    assert provider.calls == calls


def test_fork_of_fork_retains_intervention_and_can_override_it(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)
    client = ChatClient(MockProvider())

    def flow(text):
        return client.create(model="mock", messages=[{"role": "user", "content": text}],
                             temperature=0)

    original = engine.run(flow, "original")
    first = engine.run(flow, "original", source=original, fork=Fork(1, {"prompt": "edited"}))
    second = engine.run(flow, "original", source=first, fork=Fork(1, {"model": "new"}))
    request = store.steps(second)[0]["request"]["payload"]
    assert request["model"] == "new"
    assert request["messages"][0]["content"] == "edited"
    assert store.get_run(second)["status"] == "completed"


def test_tool_override_lineage_restores_state_in_descendant_prefix(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)
    calls = []

    @step
    def first(value):
        calls.append(value)
        current_session().state["n"] = value
        return value

    @step
    def last(value):
        return value * 2

    def flow(value):
        return last(first(value))

    original = engine.run(flow, 1)
    forked = engine.run(flow, 1, source=original, fork=Fork(1, {
        "tool_result": 9, "state_after": {"n": 9}}))
    descendant = engine.run(flow, 1, source=forked, fork=Fork(2, {"tool_result": 25}))
    assert store.get_run(descendant)["output"] == 25
    assert store.steps(descendant)[0]["state_after"] == {"n": 9}
    assert calls == [1]
