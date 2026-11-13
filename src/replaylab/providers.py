"""Pluggable deterministic mock and non-streaming OpenAI-compatible HTTP adapter."""

from typing import Protocol
from urllib.parse import urlsplit

import httpx

from replaylab.engine import current_session
from replaylab.store import request_key


class Provider(Protocol):
    namespace: str

    def complete(self, request: dict) -> dict: ...


class OpenAIProvider:
    def __init__(self, base_url: str, api_key: str, *, http: httpx.Client | None = None):
        url = urlsplit(base_url)
        if (url.scheme not in {"https", "http"} or not url.hostname
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("base_url must be an HTTP(S) URL without credentials/query/fragment")
        if not api_key.strip():
            raise ValueError("API key is required")
        self.base_url = base_url.rstrip("/")
        self.namespace = f"openai-compatible:{self.base_url}"
        self._api_key = api_key
        self._http = http

    def complete(self, request: dict) -> dict:
        def send(http):
            response = http.post(
                f"{self.base_url}/chat/completions", json=request,
                headers={"Authorization": f"Bearer {self._api_key}"}, timeout=60,
            )
            response.raise_for_status()
            body = response.json()
            if (not isinstance(body, dict) or not isinstance(body.get("choices"), list)
                    or not body["choices"]
                    or not isinstance(body["choices"][0].get("message"), dict)):
                raise ValueError("Provider returned no chat completion message")
            return body

        if self._http is not None:
            return send(self._http)
        with httpx.Client() as http:
            return send(http)


class MockProvider:
    """Offline fixture, not a language model. Task markers drive the research demo."""
    namespace = "replaylab:synthetic-mock:v1"

    def __init__(self):
        self.calls = 0

    def complete(self, request: dict) -> dict:
        self.calls += 1
        messages = request["messages"]
        system = "\n".join(m.get("content", "") for m in messages if m["role"] == "system")
        prompt = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if "task:plan" in system:
            text = "Compare embedded SQLite with a server database for offline trace storage."
        elif "task:summarize" in system:
            text = "[S1] SQLite: embedded, offline, single writer. [S2] ServerDB: multi-user service."
        elif "task:answer" in system:
            if "Cite only source IDs" not in prompt:
                raise ValueError("Citation policy failed: step 4 prompt omitted source grounding")
            text = "Choose SQLite for a single-user offline trace: no server required [S1]."
        else:
            text = f"Mock response: {prompt}"
        return {
            "id": f"mock-{request_key(request)[:12]}",
            "object": "chat.completion", "model": request["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


class ChatClient:
    """Drop-in call shape: client.chat.completions.create(...); returns JSON dicts."""
    def __init__(self, provider: Provider):
        self.provider = provider
        self.chat = self
        self.completions = self

    def create(self, *, model: str, messages: list[dict], **params) -> dict:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonempty string")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a nonempty list")
        if any(not isinstance(m, dict) or not isinstance(m.get("role"), str)
               or not isinstance(m.get("content"), str) for m in messages):
            raise ValueError("messages require string role and content (text-only)")
        if params.pop("stream", False):
            raise ValueError("Streaming is not supported; record complete responses")
        request = {"model": model, "messages": messages, **params}
        return current_session().call(
            "llm", "chat.completions.create", "1", request, self.provider.complete,
            namespace=self.provider.namespace,
        )
