from replaylab.demo import FIXED_PROMPT, research_workflow, run_demo
from replaylab.engine import Engine, Fork
from replaylab.providers import MockProvider
from replaylab.store import Store


def test_fixed_prompt_retains_evidence_in_system_context(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    result = run_demo(store)
    request = store.steps(result["fork"])[3]["request"]["payload"]
    system = request["messages"][0]["content"]
    assert "[S1]" in system
    assert "No server required" in system
    assert request["messages"][-1]["content"] == FIXED_PROMPT


def test_tool_override_changes_downstream_summary(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)
    flow = research_workflow(MockProvider())
    data = {"question": "offline storage?"}
    original = engine.run(flow, data)
    forked = engine.run(
        flow,
        data,
        source=original,
        fork=Fork(
            2,
            {
                "tool_result": [
                    {
                        "id": "X1",
                        "title": "Alternative synthetic source",
                        "text": "Different evidence.",
                    }
                ]
            },
        ),
    )
    summary = store.steps(forked)[2]["output"]["choices"][0]["message"]["content"]
    assert "[X1]" in summary
    assert "Different evidence" in summary
    assert "[S1]" not in summary
