"""Static architecture regressions for updater-owned Random provider boundaries."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_engine_startup_is_read_only_random_consumer() -> None:
    """Positive/negative: startup opens Random read-only and contains no build fallback."""
    source = (ROOT / "engine/server/api/server.py").read_text()
    assert "open_random_provider_readonly" in source
    assert "random_cache_db = None" in source
    assert "bootstrap_engine_random_cache_db" not in source
    assert "populate_random_cache" not in source


def test_paged_random_owns_only_random_cache_lock() -> None:
    """Positive/negative: joined Random pagination cannot nest the main DB lock."""
    source = (ROOT / "engine/server/api/services/discovery_service.py").read_text()
    start = source.index("def _handle_random")
    end = source.index("def handle_internal_discovery", start)
    body = source[start:end]
    assert "with server.random_cache_lock" in body
    assert "server.db_lock" not in body
    assert "fetch_random_provider_range" in body


def test_random_runtime_has_no_hot_reload_or_startup_refresh_switch() -> None:
    """Positive/negative: runtime uses read-only Random startup without obsolete smoke flags."""
    server = (ROOT / "engine/server/api/server.py").read_text().lower()
    config = (ROOT / "engine/server/api/server_config.py").read_text()
    smoke = (ROOT / "tests/run-arch-split-smoke.sh").read_text()
    assert "random_cache_db.close()" in server
    assert "DEFAULT_RANDOM_CACHE_REFRESH" not in config
    assert '"${ROOT_DIR}/engine/server/api/server.py"' in smoke
    assert '--host "${ENGINE_HOST}" --port "${ENGINE_PORT}"' in smoke
    assert "--random-cache-refresh" not in smoke
    assert "--no-random-cache-refresh" not in smoke
    assert "watchdog" not in server
    assert "inotify" not in server
    assert "random_cache_mtime" not in server

def test_random_publication_contract_is_documented_offline_without_hot_reload() -> None:
    """Positive/negative: supported production publication is stop/build/start, not hot replacement."""
    data_build = (ROOT / "docs/DATA_BUILD.md").read_text().lower()
    deployment = (ROOT / "docs/DEPLOYMENT.md").read_text().lower()
    architecture = (ROOT / "docs/ARCHITECTURE.md").read_text().lower()

    assert "offline operation" in data_build
    assert "stop engine" in data_build and "restart" in data_build
    assert "does not hot-reload" in data_build
    assert "no hot reload is supported" in deployment
    assert "offline stop -> build/validate/atomic-replace -> start" in architecture
