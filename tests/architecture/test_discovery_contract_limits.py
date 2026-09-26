"""Architecture regressions for Discovery page-limit ownership boundaries."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _constant(path: Path, name: str) -> object:
    """Read one top-level literal constant without importing runtime dependencies."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"missing constant {name} in {path}")


def test_paged_discovery_contract_owns_20_50_limits_independently() -> None:
    """Fresh/Popular/Random page policy must not inherit recommendation batch size."""
    path = ROOT / "engine/server/api/services/discovery_service.py"
    source = path.read_text()

    assert _constant(path, "DISCOVERY_DEFAULT_LIMIT") == 20
    assert _constant(path, "DISCOVERY_MAX_LIMIT") == 50
    assert "server.default_limit" not in source
    assert "BATCH_SIZE" not in source


def test_finite_recommendation_batch_still_fits_one_public_fetch() -> None:
    """The temporary one-shot Recommended bridge remains explicitly bounded by Client 50."""
    config = (ROOT / "engine/server/api/recommendations/config.py").read_text()
    client = ROOT / "client/backend/services/discovery_v1.py"

    # The configured Home profile is the source of BATCH_SIZE; guard the current
    # concrete value without importing the recommendation graph into this test.
    assert '"home": {' in config
    assert '"batch_size": 48' in config
    assert _constant(client, "MAX_LIMIT") == 50
    assert 48 <= 50
