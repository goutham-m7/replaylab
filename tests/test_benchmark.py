from replaylab.benchmark import benchmark


def test_benchmark_reports_measured_execution_counts():
    result = benchmark(2)
    assert result["trials"] == 2
    assert result["provider_calls"] == {"record": 6, "fork": 2, "replay": 0, "warm_fork": 0}
    assert result["prefix_steps_replayed"] == 6
    for name in ("record", "fork", "replay", "warm_fork"):
        assert result["latency_ms"][name]["median"] > 0
        assert result["latency_ms"][name]["p95"] >= result["latency_ms"][name]["median"]
