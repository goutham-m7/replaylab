import math

import pytest

from replaylab.store import Store, canonical, request_key


def test_keys_are_order_independent_but_type_sensitive():
    assert request_key({"a": 1, "b": [2]}) == request_key({"b": [2], "a": 1})
    assert request_key({"a": 1}) != request_key({"a": "1"})


@pytest.mark.parametrize("value", [math.nan, math.inf, object(), {1: "bad"}])
def test_rejects_non_json(value):
    with pytest.raises((ValueError, TypeError)):
        canonical(value)


def test_store_round_trip_and_missing_run(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    run = store.create_run("example", {"question": "q"}, "record", None, None)
    store.finish_run(run, "completed", {"answer": 42}, None)
    assert store.get_run(run)["output"] == {"answer": 42}
    assert store.list_runs()[0]["id"] == run
    assert store.steps(run) == []
    with pytest.raises(KeyError):
        store.get_run("missing")


def test_unknown_schema_rejected(tmp_path):
    import sqlite3

    path = tmp_path / "new.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="schema"):
        Store(path)
