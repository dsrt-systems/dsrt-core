# core/routing/profiles/registry.py
"""
C9 Routing Profile Registry (§20–21).

Manages built-in and custom routing profiles.
"""

from __future__ import annotations

from core.routing.contracts import (
    BUILTIN_PROFILES,
    RoutingProfile,
)


class RoutingProfileRegistry:
    """Registry for routing profiles.

    Pre-loaded with the 5 built-in profiles from contracts.
    Custom profiles can be registered at runtime.

    Usage::

        registry = RoutingProfileRegistry()
        profile = registry.get("builtin_fast")
        all_profiles = registry.list_all()
    """

    def __init__(self) -> None:
        self._profiles: dict[str, RoutingProfile] = dict(BUILTIN_PROFILES)

    def get(self, profile_id: str) -> RoutingProfile | None:
        """Get a profile by ID."""
        return self._profiles.get(profile_id)

    def get_or_default(
        self, profile_id: str | None
    ) -> RoutingProfile:
        """Get a profile by ID, falling back to BALANCED."""
        if profile_id and profile_id in self._profiles:
            return self._profiles[profile_id]
        return self._profiles["builtin_balanced"]

    def register(self, profile: RoutingProfile) -> None:
        """Register a custom profile."""
        if profile.profile_id in BUILTIN_PROFILES:
            raise ValueError(
                f"Cannot override built-in profile '{profile.profile_id}'"
            )
        self._profiles[profile.profile_id] = profile

    def list_all(self) -> list[RoutingProfile]:
        """List all registered profiles."""
        return list(self._profiles.values())

    def list_builtin(self) -> list[RoutingProfile]:
        """List only built-in profiles."""
        return list(BUILTIN_PROFILES.values())

    def has(self, profile_id: str) -> bool:
        return profile_id in self._profiles

    @property
    def count(self) -> int:
        return len(self._profiles)