# Implementation and test plan

1. Establish packaging, license, design and CI.
2. Test then implement canonical serialization and SQLite storage.
3. Test then implement leaf step execution, replay, forks and state restoration.
4. Test then implement mock and HTTP providers and compatible client.
5. Build synthetic failing research workflow, CLI and diff.
6. Test then implement FastAPI endpoints and local security boundaries.
7. Build and exercise timeline/inspector/fork/diff frontend in browser.
8. Capture actual demo, coverage and benchmark; document SDK, tradeoffs and limits.

Tests own behavior at the smallest boundary: Store integration uses actual SQLite;
Engine integration uses real Store plus counting callables; HTTP tests replace only
network transport; API tests use TestClient; CLI tests invoke installed executable.
No database mocks. Happy/error paths cover JSON contracts, missing runs, invalid edits,
cache divergence, cached failures and unsafe web origins. Browser covers rendered
navigation and edits. Not tested: remote LLM quality, OS termination timing, framework
internals; these do not belong to the promised sequential replay contract.
