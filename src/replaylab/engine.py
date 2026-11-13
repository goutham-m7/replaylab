"""Sequential workflow replay. Only decorated leaf boundaries may have effects."""

import inspect
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from time import perf_counter

from replaylab.store import Store, canonical, clone, request_key

_ACTIVE = ContextVar("replaylab_session", default=None)


class ReplayDivergence(RuntimeError):
    """The live workflow no longer matches the recorded prefix."""


class RecordedFailure(RuntimeError):
    """An exception reproduced from a recorded boundary without executing it."""


@dataclass(frozen=True)
class Fork:
    position: int
    changes: dict

    def __post_init__(self):
        if isinstance(self.position, bool) or not isinstance(self.position, int) or self.position < 1:
            raise ValueError("Fork position must be a positive integer")
        if not isinstance(self.changes, dict):
            raise ValueError("Fork changes must be an object")
        allowed = {"prompt", "model", "params", "tool_result", "state_after"}
        if not self.changes or self.changes.keys() - allowed:
            raise ValueError("Specify prompt, model, params, or tool_result")
        if "tool_result" in self.changes:
            if self.changes.keys() - {"tool_result", "state_after"}:
                raise ValueError("Tool results cannot be combined with LLM edits")
        elif "state_after" in self.changes:
            raise ValueError("state_after requires tool_result")
        for field in ("prompt", "model"):
            if field in self.changes and (
                not isinstance(self.changes[field], str) or not self.changes[field].strip()
            ):
                raise ValueError(f"{field} must be a nonempty string")
        if "params" in self.changes:
            params = self.changes["params"]
            if not isinstance(params, dict) or params.keys() & {"model", "messages", "stream"}:
                raise ValueError("params must be an object without model/messages/stream")
        if "state_after" in self.changes and not isinstance(self.changes["state_after"], dict):
            raise ValueError("state_after must be an object")
        canonical(self.changes)

    def validate_kind(self, kind):
        if ("tool_result" in self.changes) != (kind == "tool"):
            raise ValueError("Use tool_result for tools; prompt/model/params for LLM steps")

    def apply(self, request):
        self.validate_kind(request["kind"])
        result = clone(request)
        if request["kind"] == "llm":
            payload = result["payload"]
            if "prompt" in self.changes:
                users = [m for m in payload["messages"] if m.get("role") == "user"]
                if not users:
                    raise ValueError("Prompt edit requires a user message")
                users[-1]["content"] = self.changes["prompt"]
            if "model" in self.changes:
                payload["model"] = self.changes["model"]
            payload.update(self.changes.get("params", {}))
        else:
            # Overrides have their own identity and never poison the real tool cache.
            result["override"] = self.changes
        return result


def current_session():
    session = _ACTIVE.get()
    if session is None:
        raise RuntimeError("Run traced steps inside Engine.run()")
    return session


class Session:
    def __init__(self, store, run_id, mode, source_steps, fork):
        self.store = store
        self.run_id = run_id
        self.mode = mode
        self.source_steps = source_steps
        self.fork = fork
        self.state = {}
        self.position = 0
        self.in_step = False

    def call(self, kind, name, version, payload, execute, namespace="local"):
        if self.in_step:
            raise RuntimeError("Nested steps are not supported; decorate leaf boundaries only")
        before = clone(self.state)
        if not isinstance(before, dict):
            raise TypeError("Session state must be a JSON object")
        request = clone(dict(kind=kind, name=name, version=version, namespace=namespace,
                             payload=payload, state=before))
        self.position += 1
        position = self.position
        at_fork = self.fork is not None and position == self.fork.position
        intervention = {}
        if position <= len(self.source_steps):
            previous = self.source_steps[position - 1]["request"]
            identity = ("kind", "name", "version", "namespace")
            if all(previous[field] == request[field] for field in identity):
                intervention = clone(previous.get("intervention", {}))
        if at_fork:
            merged_params = {**intervention.get("params", {}),
                             **self.fork.changes.get("params", {})}
            intervention.update(self.fork.changes)
            if merged_params:
                intervention["params"] = merged_params
        if intervention:
            base_key = request_key(request)
            request = Fork(position, intervention).apply(request)
            request.update(intervention=intervention, base_key=base_key)
        key = request_key(request)
        start = perf_counter()
        output = error = None
        origin = "executed"
        self.in_step = True
        try:
            prefix = self.fork is not None and position < self.fork.position
            if self.mode == "replay" or prefix:
                if position > len(self.source_steps):
                    raise ReplayDivergence(f"No recorded step at position {position}")
                old = self.source_steps[position - 1]
                if old["key"] != key:
                    raise ReplayDivergence(f"Request diverged at step {position}: {name}")
                origin = "replayed"
                self.state = clone(old["state_after"])
                if old["error"] is not None:
                    raise RecordedFailure(f"{old['error']['type']}: {old['error']['message']}")
                output = clone(old["output"])
            elif "tool_result" in intervention:
                origin = "overridden"
                output = clone(intervention["tool_result"])
                self.state = clone(intervention.get("state_after", before))
            else:
                cached = self.store.cached(key) if self.fork is not None else None
                if cached is not None:
                    origin = "cached"
                    output = clone(cached["output"])
                    self.state = clone(cached["state_after"])
                else:
                    output = clone(execute(request["payload"]))
            canonical(self.state)
            return output
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            self.in_step = False
            try:
                after = clone(self.state)
            except (TypeError, ValueError):
                # Preserve the failure trace even when a tool violated the JSON contract.
                self.state = after = before
            self.store.append_step(self.run_id, dict(
                position=position, kind=kind, name=name, key=key, request=request,
                output=output, error=error, state_before=before, state_after=after,
                origin=origin, duration_ms=round((perf_counter() - start) * 1000, 3),
            ))


class Engine:
    def __init__(self, store: Store):
        self.store = store

    def run(self, workflow, input, *, mode="record", source=None, fork=None, name=None):
        if mode not in {"record", "replay"}:
            raise ValueError("mode must be record or replay")
        if mode == "replay" and (source is None or fork is not None):
            raise ValueError("Replay requires a source and cannot have a fork edit")
        if fork is not None and source is None:
            raise ValueError("Fork requires a source run")
        if source is not None and mode == "record" and fork is None:
            raise ValueError("Source requires replay mode or a fork edit")
        if _ACTIVE.get() is not None:
            raise RuntimeError("Nested Engine.run is not supported")
        if inspect.iscoroutinefunction(workflow):
            raise TypeError("async workflows are not supported")
        input = clone(input)
        source_steps = self.store.steps(source) if source else []
        if fork is not None:
            if fork.position > len(source_steps):
                raise ValueError("Fork position is outside the source trace")
            fork.validate_kind(source_steps[fork.position - 1]["kind"])
        fork_json = None if fork is None else dict(position=fork.position, changes=fork.changes)
        run_id = self.store.create_run(name or workflow.__name__, input,
                                       "fork" if fork else mode, source, fork_json)
        session = Session(self.store, run_id, mode, source_steps, fork)
        token = _ACTIVE.set(session)
        try:
            output = clone(workflow(input))
            required = len(source_steps) if mode == "replay" else (fork.position if fork else 0)
            if session.position < required:
                raise ReplayDivergence("Workflow ended before consuming the recorded prefix")
            self.store.finish_run(run_id, "completed", output, None)
        except Exception as exc:
            self.store.finish_run(run_id, "failed", None,
                                  {"type": type(exc).__name__, "message": str(exc)})
        finally:
            _ACTIVE.reset(token)
        return run_id


def step(function=None, *, name=None, version="1"):
    """Trace a synchronous leaf function; arguments and result must be JSON values."""
    def decorate(fn):
        if inspect.iscoroutinefunction(fn):
            raise TypeError("async steps are not supported")
        signature = inspect.signature(fn)
        step_name = name or f"{fn.__module__}.{fn.__qualname__}"

        @wraps(fn)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            payload = {"arguments": dict(bound.arguments)}
            return current_session().call(
                "tool", step_name, version, payload, lambda _: fn(*args, **kwargs)
            )
        return wrapped
    return decorate(function) if function is not None else decorate
