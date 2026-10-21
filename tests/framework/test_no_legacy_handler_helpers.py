"""Static guard against reintroducing legacy handler-shaped HTTP adapters."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = (
    ROOT / "client" / "backend",
    ROOT / "engine" / "server" / "api",
    ROOT / "tests" / "client_backend",
    ROOT / "tests" / "engine_api",
    ROOT / "tests" / "framework",
)

# Keep these tokens assembled so the source grep used by FastAPI response-helper cleanup does not
# report this guard as an offender while the test still checks exact strings.
FORBIDDEN_TOKENS = (
    "Response" + "HandlerProtocol",
    "FastAPI" + "HandlerAdapter",
    "adapter" + "_response",
    "send" + "_response",
    "send" + "_header",
    "end" + "_headers",
    "respond" + "_json(handler",
    "respond" + "_bytes(handler",
    "respond" + "_options(handler",
    "read" + "_json_body(handler",
)

FORBIDDEN_DOT_TOKENS = (".r" + "file", ".w" + "file")
ALLOWED_DOT_TOKEN_FILES = {
    # This fixture is a fake external Engine HTTP server used by Client backend
    # gateway tests. It is a network-boundary fake, not an internal project
    # route adapter, so socket-level request/response streams are allowed here.
    ROOT / "tests" / "client_backend" / "conftest.py",
}


def _python_files() -> list[Path]:
    """Collect source files covered by the legacy-handler static guard."""
    files: list[Path] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path == Path(__file__).resolve():
                continue
            files.append(path)
    return sorted(files)


def test_no_legacy_handler_named_helpers_remain() -> None:
    """Reject legacy handler-helper names in production and internal tests."""
    offenders: list[str] = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {token!r}")
    assert offenders == []


def test_no_internal_route_fake_stream_state_remains() -> None:
    """Reject fake route-handler streams except at documented network fakes."""
    offenders: list[str] = []
    for path in _python_files():
        if path in ALLOWED_DOT_TOKEN_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_DOT_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {token!r}")
    assert offenders == []
