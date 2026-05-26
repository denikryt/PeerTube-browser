.PHONY: test test-fast test-python test-boundaries test-python-compile test-legacy-interaction-events build-frontend build-crawler test-smoke-arch test-installers-dry-run lint

test: test-fast

test-fast: test-python-compile test-legacy-interaction-events test-boundaries test-python

test-python-compile:
	python3 -m compileall client/backend engine/server

test-legacy-interaction-events:
	python3 engine/server/db/jobs/tests/test-interaction-events.py

test-boundaries:
	bash tests/check-client-engine-boundary.sh
	bash tests/check-frontend-client-gateway.sh

test-python:
	python3 -m pytest -q

build-frontend:
	cd client/frontend && npm run build

build-crawler:
	cd engine/crawler && npm run build

test-smoke-arch:
	bash tests/run-arch-split-smoke.sh

test-installers-dry-run:
	bash tests/run-installers-smoke.sh --dry-run-only

lint:
	python3 -m ruff check tests/contracts client/backend/lib/http_utils.py client/backend/lib/time_utils.py client/backend/server.py client/backend/repositories client/backend/services client/backend/schemas.py engine/server/api/handlers/similar.py engine/server/api/routes engine/server/api/services tests/engine_api/conftest.py tests/engine_api/test_engine_route_dispatch_characterization.py tests/engine_api/test_channels_route_characterization.py tests/engine_api/test_internal_video_routes_characterization.py tests/engine_api/test_engine_ingest_mode_characterization.py tests/engine_api/test_similar_route_characterization.py
