"""Local-only command line. Loading a user workflow is always explicit."""

import argparse
import importlib
import json
import sys
from pathlib import Path

from replaylab.demo import research_workflow, run_demo
from replaylab.diff import compare
from replaylab.engine import Engine, Fork
from replaylab.providers import MockProvider
from replaylab.store import Store


def load_workflow(spec: str):
    if spec == "research":
        return research_workflow(MockProvider())
    if ":" not in spec:
        raise ValueError("Workflow must be research or an explicit module:function")
    module, symbol = spec.split(":", 1)
    workflow = getattr(importlib.import_module(module), symbol)
    if not callable(workflow):
        raise ValueError("Workflow entrypoint is not callable")
    return workflow


def parser():
    root = argparse.ArgumentParser(description="Time-travel debugging for LLM workflows")
    commands = root.add_subparsers(dest="command", required=True)
    for command in ("demo", "runs", "inspect", "diff", "run", "replay", "fork", "serve"):
        sub = commands.add_parser(command)
        sub.add_argument("--db", type=Path, default=Path(".replaylab/traces.sqlite"))
        if command in {"replay", "fork", "serve"}:
            sub.add_argument("--app", action="append", default=[], metavar="MODULE:FUNCTION",
                             help="Explicitly trust/register a workflow (repeatable)")
        if command in {"inspect", "replay", "fork"}:
            sub.add_argument("run_id")
        if command == "demo":
            sub.add_argument("--json", action="store_true")
        elif command == "inspect":
            sub.add_argument("--step", type=int)
        elif command == "diff":
            sub.add_argument("left")
            sub.add_argument("right")
        elif command == "run":
            sub.add_argument("workflow")
            sub.add_argument("--input", required=True, help="JSON workflow input")
        elif command == "fork":
            sub.add_argument("--step", type=int, required=True)
            sub.add_argument("--edit", required=True, help="JSON prompt/model/params/tool_result edit")
        elif command == "serve":
            sub.add_argument("--port", type=int, default=8765)
    bench = commands.add_parser("benchmark")
    bench.add_argument("--trials", type=int, default=50)
    return root


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def demo_text(result, store):
    print("replaylab / offline research repair")
    print(f"Original: {result['original']} / failed at step 4")
    print(f"Fork:     {result['fork']} / {store.get_run(result['fork'])['status']}")
    print(f"Provider calls: original={result['original_provider_calls']}, "
          f"fork={result['fork_provider_calls']}")
    print(f"Prefix replayed: {result['prefix_replayed']}/3 steps (zero boundary calls)")
    print("Step  Original                       Fork")
    for row in result["diff"]["steps"]:
        left, right = row["left"], row["right"]
        a = "—" if left is None else ("error" if left["error"] else left["kind"])
        b = "—" if right is None else ("error" if right["error"] else right["origin"])
        print(f"{row['position']:>4}  {a:<29}  {b} / {row['status']}")
    print("Answer: " + store.get_run(result["fork"])["output"]["answer"])


def main():
    args = parser().parse_args()
    try:
        if args.command == "benchmark":
            from replaylab.benchmark import benchmark

            emit(benchmark(args.trials))
            return 0
        store = Store(args.db)
        engine = Engine(store)
        if args.command == "demo":
            result = run_demo(store)
            if args.json:
                emit(result)
            else:
                demo_text(result, store)
            return 0 if store.get_run(result["fork"])["status"] == "completed" else 1
        if args.command == "runs":
            emit(store.list_runs())
        elif args.command == "inspect":
            if args.step is None:
                emit(dict(run=store.get_run(args.run_id), steps=store.steps(args.run_id)))
            else:
                steps = store.steps(args.run_id)
                if args.step < 1 or args.step > len(steps):
                    raise ValueError("Step is outside the trace")
                emit(steps[args.step - 1])
        elif args.command == "diff":
            emit(compare(store, args.left, args.right))
        elif args.command == "run":
            run_id = engine.run(load_workflow(args.workflow), json.loads(args.input),
                                name=args.workflow)
            emit(store.get_run(run_id))
            return 0 if store.get_run(run_id)["status"] == "completed" else 1
        else:
            registry = {"research": load_workflow("research")}
            registry.update((spec, load_workflow(spec)) for spec in args.app)
            if args.command == "serve":
                import uvicorn

                from replaylab.web import create_app

                uvicorn.run(create_app(store, registry), host="127.0.0.1", port=args.port)
            else:
                source = store.get_run(args.run_id)
                if source["workflow"] not in registry:
                    raise ValueError("Workflow not registered; pass --app module:function")
                edit = Fork(args.step, json.loads(args.edit)) if args.command == "fork" else None
                run_id = engine.run(registry[source["workflow"]], source["input"],
                                    name=source["workflow"], source=args.run_id, fork=edit,
                                    mode="record" if edit else "replay")
                emit(store.get_run(run_id))
                return 0 if store.get_run(run_id)["status"] == "completed" else 1
        return 0
    except (ValueError, TypeError, KeyError, ImportError, AttributeError, OSError) as exc:
        print(f"replaylab: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
