"""Architecture regressions for one ServingVisibility representation across Engine queries."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[2]
ENGINE_SERVER = ROOT / "engine/server"
if str(ENGINE_SERVER) not in sys.path:
    sys.path.insert(0, str(ENGINE_SERVER))

from data.serving_moderation import ServingVisibility, serving_visibility_from_server, build_serving_visibility_sql


def test_runtime_flags_freeze_once_into_serving_visibility() -> None:
    """Positive: explicit runtime moderation flags become one immutable policy object."""
    server = SimpleNamespace(
        video_error_threshold=7,
        enable_instance_ignore=False,
        enable_channel_blocklist=True,
    )
    assert serving_visibility_from_server(server) == ServingVisibility(
        error_threshold=7,
        apply_instance_filter=False,
        apply_channel_filter=True,
    )


def test_missing_runtime_flags_use_existing_visibility_defaults() -> None:
    """Negative/boundary: absent optional runtime attributes preserve current safe defaults."""
    assert serving_visibility_from_server(SimpleNamespace()) == ServingVisibility(
        error_threshold=None,
        apply_instance_filter=True,
        apply_channel_filter=True,
    )


def test_exact_availability_is_independent_of_legacy_threshold():
    """Both policy branches enforce SQL NULL rather than admitting empty-string reasons."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE videos(invalid_reason TEXT,error_count INTEGER)")
    conn.executemany(
        "INSERT INTO videos VALUES(?,?)", [(None, 0), ("", 0), ("gone", 0), (None, 10)]
    )
    for threshold, count in [(None, 2), (3, 1)]:
        sql, args = build_serving_visibility_sql("v", ServingVisibility(threshold, False, False))
        assert "COALESCE" not in sql
        assert (
            conn.execute(f"SELECT COUNT(*) FROM videos v WHERE {sql}", args).fetchone()[0] == count
        )
    conn.close()


def test_internal_resolve_has_no_compensating_handler_query():
    """Availability belongs at seed lookup; the route must not add a second lookup or threshold."""
    import ast

    source = (ROOT / "engine/server/api/handlers/internal_client_reads.py").read_text()
    tree = ast.parse(source)
    handler = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "handle_internal_video_resolve"
    )
    body = ast.get_source_segment(source, handler)
    assert "fetch_seed_embedding" in body
    assert "SELECT" not in body and "error_threshold" not in body


def test_services_pass_policy_objects_and_data_layer_builds_sql() -> None:
    """Positive/negative: SQL fragments never cross API-service/data-query boundaries."""
    discovery = (ROOT / "engine/server/api/services/discovery_service.py").read_text()
    search = (ROOT / "engine/server/api/services/search_service.py").read_text()
    facets = (ROOT / "engine/server/api/services/video_filter_service.py").read_text()
    video_search = (ROOT / "engine/server/data/video_search.py").read_text()
    video_filters = (ROOT / "engine/server/data/video_filters.py").read_text()

    for service in (discovery, search, facets):
        assert "serving_visibility_from_server" in service
        assert "build_serving_visibility_sql" not in service
    assert "visibility: ServingVisibility" in video_search
    assert "visibility: ServingVisibility" in video_filters
    assert "build_serving_visibility_sql" in video_search
    assert "build_serving_visibility_sql" in video_filters


def test_client_like_admission_precedes_request_context_publication():
    """Client identity becomes request-local state only through canonical admission."""
    import ast
    source = (ROOT / 'engine/server/api/services/recommendation_service.py').read_text()
    tree = ast.parse(source)
    handler = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'handle_similar_request')
    calls = {n.func.id: n.lineno for n in ast.walk(handler) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert calls['_resolve_client_likes'] < calls['set_request_client_likes']
    resolver = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_resolve_client_likes')
    body = ast.get_source_segment(source, resolver)
    assert 'WHERE invalid_reason IS NULL AND ({conditions})' in body
    assert 'error_count' not in body
