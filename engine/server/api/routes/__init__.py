"""Route adapters for the stdlib Engine API handler.

The modules in this package keep HTTP route-specific request parsing and
response selection out of ``handlers.similar`` while preserving the existing
``BaseHTTPRequestHandler`` runtime and public Engine API contracts.
"""
