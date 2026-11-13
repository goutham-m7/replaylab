from replaylab import Engine, Store, step


def test_replay_detects_changed_pure_output_even_when_all_requests_match(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)

    @step
    def tool(value):
        return value

    original = engine.run(lambda x: {"answer": tool(x)}, 1)
    replay = engine.run(lambda x: {"changed": tool(x)}, 1, source=original, mode="replay")
    assert store.get_run(replay)["status"] == "failed"
    assert store.get_run(replay)["error"]["type"] == "ReplayDivergence"
    assert store.steps(replay)[0]["origin"] == "replayed"


def test_replay_cannot_turn_recorded_failure_into_success_by_swallowing_it(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)

    @step
    def bad(_):
        raise ValueError("recorded failure")

    original = engine.run(bad, None)

    def swallowing(value):
        try:
            bad(value)
        except RuntimeError:
            return "silenced"

    replay = engine.run(swallowing, None, source=original, mode="replay")
    assert store.get_run(replay)["status"] == "failed"
    assert store.get_run(replay)["error"]["type"] == "ReplayDivergence"
