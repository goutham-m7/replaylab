import json
import subprocess


def cli(*args):
    return subprocess.run(["replaylab", *args], capture_output=True, text=True)


def test_demo_cli_and_inspection_commands(tmp_path):
    db = str(tmp_path / "demo.sqlite")
    demo = cli("demo", "--db", db, "--json")
    assert demo.returncode == 0, demo.stderr
    result = json.loads(demo.stdout)
    assert result["prefix_replayed"] == 3
    runs = cli("runs", "--db", db)
    assert result["original"] in runs.stdout
    inspect = cli("inspect", result["original"], "--step", "4", "--db", db)
    assert json.loads(inspect.stdout)["error"]["type"] == "ValueError"
    diff = cli("diff", result["original"], result["fork"], "--db", db)
    assert json.loads(diff.stdout)["changed"] == 2


def test_cli_missing_run_and_invalid_json_fail_cleanly(tmp_path):
    db = str(tmp_path / "trace.sqlite")
    result = cli("inspect", "missing", "--db", db)
    assert result.returncode == 2
    assert "Run not found" in result.stderr
    assert "Traceback" not in result.stderr
    invalid = cli("run", "research", "--input", "not-json", "--db", db)
    assert invalid.returncode == 2


def test_cli_records_failure_and_forks_from_json_edit(tmp_path):
    db = str(tmp_path / "trace.sqlite")
    original = cli("run", "research", "--input", '{"question":"offline?"}', "--db", db)
    assert original.returncode == 1
    run_id = json.loads(original.stdout)["id"]
    fork = cli(
        "fork",
        run_id,
        "--step",
        "4",
        "--edit",
        '{"prompt":"Cite only source IDs from supplied evidence"}',
        "--db",
        db,
    )
    assert fork.returncode == 0, fork.stderr
    assert json.loads(fork.stdout)["status"] == "completed"
    replay = cli("replay", run_id, "--db", db)
    assert replay.returncode == 1
    assert json.loads(replay.stdout)["error"]["type"] == "RecordedFailure"
