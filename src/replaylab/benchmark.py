"""Offline measurements with a fresh SQLite database per trial; no simulated latency."""

import math
import platform
import statistics
import tempfile
from pathlib import Path
from time import perf_counter

from replaylab.demo import FIXED_PROMPT, QUESTION, research_workflow
from replaylab.engine import Engine, Fork
from replaylab.providers import MockProvider
from replaylab.store import Store


def benchmark(trials: int = 50) -> dict:
    if isinstance(trials, bool) or not isinstance(trials, int) or not 1 <= trials <= 1000:
        raise ValueError("trials must be an integer between 1 and 1000")
    samples = {name: [] for name in ("record", "fork", "replay", "warm_fork")}
    counts = dict.fromkeys(samples, 0)
    prefix_steps = 0
    with tempfile.TemporaryDirectory(prefix="replaylab-bench-") as folder:
        for trial in range(trials):
            store = Store(Path(folder) / f"{trial}.sqlite")
            engine = Engine(store)
            provider = MockProvider()
            flow = research_workflow(provider)
            data = {"question": QUESTION}
            original = repaired = None
            for name in samples:
                before = provider.calls
                start = perf_counter()
                if name == "record":
                    run_id = original = engine.run(flow, data)
                elif name == "replay":
                    run_id = engine.run(flow, data, mode="replay", source=repaired)
                else:
                    run_id = engine.run(
                        flow, data, source=original, fork=Fork(4, {"prompt": FIXED_PROMPT})
                    )
                    if name == "fork":
                        repaired = run_id
                samples[name].append((perf_counter() - start) * 1000)
                counts[name] += provider.calls - before
                expected = "failed" if name == "record" else "completed"
                if store.get_run(run_id)["status"] != expected:
                    raise RuntimeError(f"Benchmark {name} did not produce {expected}")
                if name == "fork":
                    prefix_steps += sum(s["origin"] == "replayed" for s in store.steps(run_id))
    latency = {}
    for name, values in samples.items():
        ordered = sorted(values)
        latency[name] = {
            "median": round(statistics.median(values), 3),
            "p95": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        }
    return {
        "trials": trials,
        "provider": "deterministic mock (no artificial delay)",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "latency_ms": latency,
        "provider_calls": counts,
        "prefix_steps_replayed": prefix_steps,
        "method": "fresh database per trial; schema setup excluded; real SQLite commits included",
    }
