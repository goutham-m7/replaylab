import json
import os
import subprocess
from pathlib import Path


def test_custom_workflow_cli_registration_and_replay(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root), "REPLAYLAB_PROVIDER": "mock"}
    db = str(tmp_path / "example.sqlite")
    command = [
        "replaylab",
        "run",
        "examples.agent:workflow",
        "--input",
        '{"topic":"offline tracing"}',
        "--db",
        db,
    ]
    recorded = subprocess.run(command, text=True, capture_output=True, env=env)
    assert recorded.returncode == 0, recorded.stderr
    run_id = json.loads(recorded.stdout)["id"]
    replayed = subprocess.run(
        ["replaylab", "replay", run_id, "--app", "examples.agent:workflow", "--db", db],
        text=True,
        capture_output=True,
        env=env,
    )
    assert replayed.returncode == 0, replayed.stderr
    assert json.loads(replayed.stdout)["output"] == json.loads(recorded.stdout)["output"]
