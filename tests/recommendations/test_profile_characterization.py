"""Characterize recommendation profile resolution behavior."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from recommendations.profile import resolve_profile_config, resolve_profile_config_with_guest  # noqa: E402


def _config() -> dict:
    """Build a profile config with current guest/default fallback names."""
    return {
        "default_profile": "home",
        "profiles": {
            "home": {"name": "home"},
            "upnext": {"name": "upnext"},
            "guest_home": {"name": "guest_home"},
            "guest_upnext": {"name": "guest_upnext"},
            "guest": {"name": "guest"},
        },
    }


def test_resolve_profile_config_uses_explicit_mode_then_default() -> None:
    """Explicit modes win, otherwise current default_profile fallback is used."""
    assert resolve_profile_config(_config(), "upnext")["name"] == "upnext"
    assert resolve_profile_config(_config(), "missing")["name"] == "home"


def test_resolve_profile_config_with_guest_selects_guest_profiles_without_likes() -> None:
    """Guest profile selection protects new-user recommendation behavior."""
    assert resolve_profile_config_with_guest(_config(), "home", has_likes=False)[0] == "guest_home"
    assert resolve_profile_config_with_guest(_config(), "upnext", has_likes=False)[0] == "guest_upnext"
    assert resolve_profile_config_with_guest(_config(), "home", has_likes=True)[0] == "home"
