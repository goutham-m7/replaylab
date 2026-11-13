# Replaylab design

## Problem and scope
LLM agent failures are expensive to reproduce. Record synchronous, sequential Python
workflows as immutable SQLite runs, inspect the failure, change one boundary, and
re-run the suffix without repeating earlier tool effects or provider calls.
All implementation and synthetic fixtures are original to this project.

## Architecture and data flow
`workflow(input)` -> context-local Session -> leaf `@step` / ChatClient -> SQLite.
FastAPI serves a dependency-free frontend and delegates replay/fork to Engine.
The CLI explicitly registers trusted workflow callables; database content never imports code.

Choose Python 3.12, standard-library SQLite, FastAPI, and vanilla JS: one process,
no database service or frontend build. A React stack adds no value to a timeline;
checkpoints of arbitrary Python stacks would require unsafe serialization. Instead,
re-enter the workflow and verify/replay its prefix. JSON is the entire data contract.

## Execution contract
- Record mode executes every boundary, even when a matching cached value exists.
- SHA-256 keys cover canonical JSON: kind, stable name, version, provider namespace,
  arguments, and incoming state. Adapter API keys are excluded; user content is not scrubbed.
- Replay mode consumes the source run by position and matching hash, never executing
  providers or tools. A changed prefix, missing/shortened trace, changed final output,
  or swallowed source failure fails closed.
- Fork replays positions before N, applies one validated edit at N, and executes the
  suffix with content-addressed cache reuse. No cache entry exists for failures.
- Effective interventions and the pre-edit request hash travel with each boundary.
  Replaying a fork reapplies that intervention before hash validation; descendants
  inherit edits, and a new edit at the same boundary merges generation parameters.
- Prefix state is restored from recorded after-state. Cached tools also restore state.
- A tool-result override supplies its after-state explicitly or preserves incoming state.
- Steps are leaf boundaries; nested decorated steps and async functions are rejected.
  Workflow control flow, randomness, environment reads and effects outside boundaries
  remain the application's responsibility. No claim of arbitrary Python determinism.
  Only `Session.state` mutations are restored, not mutations to arbitrary arguments
  or globals. Keep workflow control flow pure and version changed tool implementations.
- Failure rows capture exception type/message and state. Replaying a failure raises a
  RecordedFailure. Each run retains status/error and completed trace, including failures.
- Each row is committed independently; interrupted runs remain marked running.

## Interfaces
`Engine(store).run(workflow, input, mode='record', source=None, fork=None)` returns a
run ID even on workflow failure. `@step` works only inside Engine execution.
`ChatClient(provider).chat.completions.create(model=..., messages=[...], **params)`
returns the OpenAI-compatible JSON response dict, not an SDK-specific object.
Providers implement `namespace` and `complete(request)`; HTTP adapter is non-streaming.
Fork edit: prompt replaces the last user message, model replaces model, params merge
non-reserved generation fields; tool_result replaces a tool's output. Step indexes are 1-based.

## Security and failure behavior
Local-only server binds loopback, enforces loopback Host headers, rejects foreign
Origins for mutations, disables CORS, and renders trace text with textContent.
No authentication: never expose it or forward its port. Trace files contain plaintext
prompts, tool outputs and snapshots; keep them out of version control. API keys come
from environment only and are passed in HTTP headers. Tool side effects after the fork
can execute again: fork only trusted, idempotent workflows. No sandbox or secret scrubber.
SQLite WAL + busy timeout handle short concurrent writes; one workflow runs sequentially.
Hashing is cache identity, not encryption. Version boundaries when implementation changes.

## Rollout and alternatives
Schema v1 initializes a new database and rejects unknown schema versions. No cloud
migration or compatibility shim. Content-addressed caching trades provider freshness
for exact replay; record mode is the explicit escape hatch. No automatic retries because
they obscure recorded boundaries and can duplicate effects.

## Acceptance criteria and evidence contract
| ID | Criterion | Proof | Observable assertion |
|---|---|---|---|
| EC-1 | Record calls, outputs, state and failures | Integration | SQLite timeline retains failed fourth step |
| EC-2 | Replay performs zero boundary calls | Integration | Counter unchanged, state restored, misses fail |
| EC-3 | Fork edits prompt/model/params/tool result | Integration | Prefix cached and changed suffix observed |
| EC-4 | CLI demo repairs a failed agent | Behavioural | Original failed, fork completed, first three cached |
| EC-5 | UI inspects, forks and compares | Behavioural | Running browser journey creates fork and displays diff |
| EC-6 | Compatible HTTP client and error handling | Integration | HTTP fixture sees body/auth; errors retained |

## Verification plan
Real temporary SQLite databases; fake only the provider network boundary using httpx
MockTransport. Test canonical hash invariance, input validation, failures, cache/state,
prefix divergence, tool override and run-length mismatch. FastAPI TestClient tests real
API routing and SQLite. CLI subprocess tests prove installed entrypoint behavior.
Run ruff, pytest coverage, demo and a real browser journey. Live paid-provider quality,
async execution, streaming, arbitrary process resurrection and multi-user auth are out
of scope, documented as limitations rather than stubs.

## Frontend design
Instrument-panel blue (#173e68), paper blue (#edf3f9), white (#ffffff), slate
(#52677c), repair orange (#ae4b16), pass teal (#17695c). System sans body, monospace
step data, compact uppercase labels. Signature: a split-rail timeline with a visible
fork seam, connecting the immutable past to an editable future. Three panes: runs,
timeline, inspector; comparison uses aligned original/fork JSON. Responsive stacked
panels, keyboard focus, native forms, no animation or external font requests.

## Interview notes

### Re-entry instead of stack snapshots
The hard part is suppressing repeated effects while preserving control flow. Restart
the trusted workflow and replay leaf results plus after-state. Reject positional/hash
drift and changed final outputs. Rejected: pickle/cloudpickle checkpoints, which are
unsafe to load, bind traces to Python internals, and do not capture external effects.
Tradeoff: synchronous, sequential workflows only; hidden time/random/global inputs
must become explicit boundary inputs or traced tools.

### Content identity instead of a position-only cache
A step number identifies a location, not a computation. Hash canonical JSON including
provider namespace, boundary version, arguments and incoming state. Record always
executes; replay never executes; forks may reuse successful suffix results. Rejected:
prompt-only hashing (wrong models/parameters/states collide), and caching failures
(temporary network errors become sticky). Cache entries store output and after-state
together. New credentials on the same endpoint are not a separate namespace: use a
separate database or an account-specific provider namespace when changing accounts.

### Branch provenance instead of rewriting the original
The original run remains unchanged. Each child points to its source and records the
effective intervention plus the unpatched hash at edited boundaries. This extra hash
matters: replacing a prompt must not hide a changed live workflow during later replay.
Rejected: mutating original request rows, which destroys the evidence needed for a diff;
and storing only a parent edit, which breaks replay when branching an existing fork.
Costs: repeated prefix rows and JSON snapshots increase storage.

### At 100× scale
First measure trace volume and writer contention; this project has not benchmarked
that load. Paginate run listings and step payloads, move large payloads to blobs keyed
by digest, and reference prefix steps instead of copying them. Introduce a single
writer queue or Postgres if concurrent writers dominate. Keep replay identity separate
from storage layout. Authentication, tenant-scoped cache namespaces, encrypted payloads,
retention, and worker isolation would be prerequisites for a shared deployment, not
optional UI additions. Async/DAG replay needs stable logical boundary IDs rather than
position; do not retrofit it by sharing a mutable sequential counter.
