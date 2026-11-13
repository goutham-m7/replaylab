import json

import httpx
import pytest

from replaylab import Engine, Fork, Store
from replaylab.providers import ChatClient, MockProvider, OpenAIProvider


def test_compatible_wrapper_prompt_model_params_fork(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    engine = Engine(store)
    provider = MockProvider()
    client = ChatClient(provider)

    def flow(question):
        return client.chat.completions.create(
            model="mock-v1", messages=[{"role": "user", "content": question}], temperature=0
        )

    original = engine.run(flow, "hello")
    forked = engine.run(
        flow,
        "hello",
        source=original,
        fork=Fork(1, {"prompt": "edited", "model": "mock-v2", "params": {"temperature": 0.5}}),
    )
    payload = store.steps(forked)[0]["request"]["payload"]
    assert payload["messages"][0]["content"] == "edited"
    assert payload["model"] == "mock-v2"
    assert payload["temperature"] == 0.5
    assert provider.calls == 2
    replay = engine.run(flow, "hello", mode="replay", source=original)
    assert store.get_run(replay)["status"] == "completed"
    assert provider.calls == 2


def test_http_adapter_sends_openai_contract_and_no_key_in_trace(tmp_path):
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "yes"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = OpenAIProvider("https://example.test/v1", "secret-test-key", http=http)
        client = ChatClient(provider)
        store = Store(tmp_path / "trace.sqlite")
        engine = Engine(store)
        run = engine.run(
            lambda text: client.chat.completions.create(
                model="local-model", messages=[{"role": "user", "content": text}]
            ),
            "question",
        )
    assert store.get_run(run)["status"] == "completed"
    assert str(observed[0].url) == "https://example.test/v1/chat/completions"
    assert observed[0].headers["authorization"] == "Bearer secret-test-key"
    assert json.loads(observed[0].content)["model"] == "local-model"
    assert "secret-test-key" not in json.dumps(store.steps(run))


@pytest.mark.parametrize("status,body", [(429, {}), (200, {}), (200, {"choices": []})])
def test_http_adapter_rejects_errors_and_malformed_responses(status, body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    ) as http:
        provider = OpenAIProvider("https://example.test/v1", "key", http=http)
        with pytest.raises((httpx.HTTPStatusError, ValueError)):
            provider.complete({"model": "x", "messages": []})


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:pass@host/v1",
        "https://host/v1?key=secret",
        "https://host/v1#fragment",
    ],
)
def test_rejects_unsafe_base_urls(url):
    with pytest.raises(ValueError):
        OpenAIProvider(url, "key")


def test_streaming_rejected_before_provider_call(tmp_path):
    provider = MockProvider()
    client = ChatClient(provider)
    store = Store(tmp_path / "trace.sqlite")
    run = Engine(store).run(
        lambda _: client.chat.completions.create(
            model="x", messages=[{"role": "user", "content": "hello"}], stream=True
        ),
        None,
    )
    assert store.get_run(run)["status"] == "failed"
    assert provider.calls == 0


def test_provider_namespace_prevents_wrong_endpoint_cache_reuse(tmp_path):
    store = Store(tmp_path / "trace.sqlite")
    a = MockProvider()
    b = MockProvider()
    b.namespace = "different-provider"
    active = [ChatClient(a)]

    def flow(text):
        return active[0].chat.completions.create(
            model="mock", messages=[{"role": "user", "content": text}]
        )

    original = Engine(store).run(flow, "hello")
    active[0] = ChatClient(b)
    replay = Engine(store).run(flow, "hello", source=original, mode="replay")
    assert store.get_run(replay)["error"]["type"] == "ReplayDivergence"
    assert b.calls == 0
