"""Loopback-only trace API. User workflow registration is explicit, never database-driven."""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from replaylab.demo import run_demo
from replaylab.diff import compare
from replaylab.engine import Engine, Fork
from replaylab.store import Store


class ForkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: Annotated[StrictInt, Field(ge=1)]
    changes: dict


def create_app(store: Store, workflows: dict[str, Callable]) -> FastAPI:
    app = FastAPI(title="Replaylab", docs_url=None, redoc_url=None, openapi_url=None)
    engine = Engine(store)
    static = Path(__file__).parent / "static"

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = urlsplit("//" + request.headers.get("host", "")).hostname
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return JSONResponse({"detail": "Loopback Host required"}, status_code=400)
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin is not None:
            expected = f"{request.url.scheme}://{request.headers['host']}"
            if origin != expected:
                return JSONResponse({"detail": "Same-origin requests only"}, status_code=403)
        response = await call_next(request)
        response.headers.update(
            {
                "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            }
        )
        return response

    @app.exception_handler(KeyError)
    async def missing(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/runs")
    def runs():
        return store.list_runs()

    @app.get("/api/runs/{run_id}")
    def inspect_run(run_id: str):
        return dict(run=store.get_run(run_id), steps=store.steps(run_id))

    @app.get("/api/diff")
    def diff(left: str, right: str):
        return compare(store, left, right)

    @app.post("/api/demo", status_code=201)
    def demo():
        return run_demo(store)

    def execute_source(run_id, edit):
        source = store.get_run(run_id)
        workflow = workflows.get(source["workflow"])
        if workflow is None:
            raise HTTPException(
                409, "Workflow is not registered; restart with --app module:function"
            )
        fork = Fork(edit.position, edit.changes) if edit else None
        result = engine.run(
            workflow,
            source["input"],
            source=run_id,
            fork=fork,
            mode="record" if fork else "replay",
            name=source["workflow"],
        )
        return store.get_run(result)

    @app.post("/api/runs/{run_id}/fork", status_code=201)
    def fork(run_id: str, body: ForkBody):
        return execute_source(run_id, body)

    @app.post("/api/runs/{run_id}/replay", status_code=201)
    def replay(run_id: str):
        return execute_source(run_id, None)

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app
