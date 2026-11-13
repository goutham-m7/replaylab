"""Small SDK example. Explicit opt-in is required before making network calls."""

import os

from replaylab import current_session, step
from replaylab.providers import ChatClient, MockProvider, OpenAIProvider


@step(name="example.lookup", version="1")
def lookup(topic: str) -> dict:
    current_session().state["topic"] = topic
    return {"source": "synthetic fixture", "note": f"{topic}: store JSON boundaries locally."}


def workflow(data: dict) -> dict:
    # Composition root: the core SDK never reads environment variables.
    provider_name = os.environ.get("REPLAYLAB_PROVIDER", "mock")
    if provider_name == "mock":
        provider = MockProvider()
        model = "mock-v1"
    elif provider_name == "openai":
        provider = OpenAIProvider(os.environ["OPENAI_BASE_URL"], os.environ["OPENAI_API_KEY"])
        model = os.environ["REPLAYLAB_MODEL"]
    else:
        raise ValueError("REPLAYLAB_PROVIDER must be mock or openai")
    evidence = lookup(data["topic"])
    result = ChatClient(provider).chat.completions.create(
        model=model, temperature=0,
        messages=[{"role": "system", "content": "Answer using only the supplied evidence."},
                  {"role": "user", "content": str(evidence)}],
    )
    return {"answer": result["choices"][0]["message"]["content"], "evidence": evidence}
