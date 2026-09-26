"""Small updater types used by tests and orchestration helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandRunner:
    """Callable command boundary used by updater tests.

    Production code uses the default subprocess runner.  Tests pass a fake runner
    to assert command arrays without shelling out to crawler, systemctl, or FAISS.
    """

    run: Callable[[Sequence[str], Path | None], None]
