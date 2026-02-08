from __future__ import annotations

from typing import Any


def resolve_profile_config(config: dict[str, Any], mode: str | None) -> dict[str, Any]:
    profiles = config.get("profiles")
    if not profiles:
        return config
    if mode and mode in profiles:
        return profiles[mode]
    default_profile = config.get("default_profile")
    if default_profile and default_profile in profiles:
        return profiles[default_profile]
    if "home" in profiles:
        return profiles["home"]
    return next(iter(profiles.values()))


def resolve_profile_config_with_guest(
    config: dict[str, Any], mode: str | None, has_likes: bool
) -> tuple[str, dict[str, Any]]:
    profiles = config.get("profiles")
    if not profiles:
        return "default", config

    if not has_likes:
        guest_mode = None
        if mode == "upnext" and "guest_upnext" in profiles:
            guest_mode = "guest_upnext"
        elif (mode is None or mode == "home") and "guest_home" in profiles:
            guest_mode = "guest_home"
        elif "guest" in profiles:
            guest_mode = "guest"
        if guest_mode:
            return guest_mode, profiles[guest_mode]

    if mode and mode in profiles:
        return mode, profiles[mode]
    default_profile = config.get("default_profile")
    if default_profile and default_profile in profiles:
        return default_profile, profiles[default_profile]
    if "home" in profiles:
        return "home", profiles["home"]
    name = next(iter(profiles.keys()))
    return name, profiles[name]
