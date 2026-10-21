"""Service helpers used by Engine API route adapters.

Services in this package own Engine API orchestration that is too large for the
HTTP dispatcher but is not low-level SQLite access or recommendation-domain
logic. They preserve current behavior during route extraction.
"""
