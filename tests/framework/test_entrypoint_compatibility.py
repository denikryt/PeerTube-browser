"""Entry-point compatibility tests for the FastAPI migration."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_client_server_help_path_remains_executable() -> None:
    """The Client backend keeps the existing server.py executable path."""
    result = subprocess.run(
        ["python3", "client/backend/server.py", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "--engine-url" in result.stdout
    assert "--publish-mode" in result.stdout


def test_engine_server_entrypoint_path_remains_present() -> None:
    """The Engine API keeps the existing server.py path and known FAISS prerequisite."""
    path = ROOT / "engine" / "server" / "api" / "server.py"
    result = subprocess.run(
        ["python3", str(path), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert path.exists()
    assert result.returncode in {0, 1}
    if result.returncode != 0:
        assert "faiss is required" in (result.stdout + result.stderr)
    else:
        assert "--host" in result.stdout
