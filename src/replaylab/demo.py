"""Entirely synthetic, offline research pipeline with a reproducible fourth-step failure."""

from replaylab.diff import compare
from replaylab.engine import Engine, Fork, current_session, step
from replaylab.providers import ChatClient, MockProvider, Provider
from replaylab.store import Store, canonical

QUESTION = "Which store suits a single-user offline agent trace?"
FIXED_PROMPT = "Cite only source IDs from the supplied evidence. Recommend an offline trace store."
SOURCES = [
    {
        "id": "S1",
        "title": "Synthetic SQLite note",
        "text": "Embedded SQL database. Works offline. One concurrent writer. No server required.",
    },
    {
        "id": "S2",
        "title": "Synthetic ServerDB note",
        "text": "Client-server database. Requires a service. Supports multiple concurrent writers.",
    },
]


@step(name="search_sources", version="1")
def search_sources(query: str) -> list[dict]:
    # A local fixture is intentional: demo never scrapes the web or sends data anywhere.
    current_session().state.update(query=query, source_ids=[s["id"] for s in SOURCES])
    return SOURCES


@step(name="validate_answer", version="1")
def validate_answer(answer: str) -> dict:
    if "[S1]" not in answer:
        raise ValueError("Answer lacks source S1")
    current_session().state["validated"] = True
    return {"answer": answer, "source_ids": ["S1"], "validated": True}


def research_workflow(provider: Provider):
    client = ChatClient(provider)

    def research(data):
        current_session().state["question"] = data["question"]

        def llm(task, prompt, evidence=""):
            response = client.chat.completions.create(
                model="mock-research-v1",
                temperature=0,
                messages=[
                    {"role": "system", "content": f"task:{task}\n{evidence}"},
                    {"role": "user", "content": prompt},
                ],
            )
            return response["choices"][0]["message"]["content"]

        plan = llm("plan", data["question"])
        sources = search_sources(plan)
        summary = llm("summarize", canonical(sources))
        answer = llm("answer", "Answer confidently without citations.", evidence=summary)
        return validate_answer(answer)

    return research


def run_demo(store: Store) -> dict:
    provider = MockProvider()
    flow = research_workflow(provider)
    engine = Engine(store)
    data = {"question": QUESTION}
    original = engine.run(flow, data, name="research")
    original_calls = provider.calls
    forked = engine.run(
        flow, data, source=original, fork=Fork(4, {"prompt": FIXED_PROMPT}), name="research"
    )
    return dict(
        original=original,
        fork=forked,
        original_provider_calls=original_calls,
        fork_provider_calls=provider.calls - original_calls,
        prefix_replayed=sum(s["origin"] == "replayed" for s in store.steps(forked)),
        diff=compare(store, original, forked),
    )
