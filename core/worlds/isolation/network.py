"""
World Network Policy Manager (C7 §22-23).

Enforces network access policies for World instances:
  - Domain allow/deny lists
  - Port restrictions
  - Rate limiting
  - Proxy routing
  - Request logging

Network Modes (C7 §23):
  OFFLINE    — No network access at all
  RESTRICTED — Only explicitly allowed domains
  CONTROLLED — Allowed domains + logging + rate limiting (default)
  OPEN       — All domains allowed (not recommended)
  PROXY      — All traffic routed through a proxy
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from schemas.domain.enums import NetworkMode
from schemas.domain.world import WorldNetworkPolicy

from core.observability.logging import get_logger


logger = get_logger("dsrt.worlds.network")


@dataclass
class NetworkRequest:
    """A network request to be evaluated against policy."""
    url: str
    method: str = "GET"
    source_component: str = ""
    world_instance_id: str = ""


@dataclass(frozen=True)
class NetworkDecision:
    """Result of a network policy evaluation."""
    allowed: bool
    reason: str = ""
    domain: str = ""
    mode: str = ""
    rate_limited: bool = False


class WorldNetworkPolicyManager:
    """Enforces network access policies for World instances (C7 §22-23).

    Usage:
        mgr = WorldNetworkPolicyManager()
        policy = WorldNetworkPolicy(
            mode=NetworkMode.CONTROLLED,
            allowed_domains=["api.example.com", "docs.example.com"],
            blocked_domains=["evil.com"],
        )
        decision = mgr.evaluate_request(
            NetworkRequest(url="https://api.example.com/data"),
            policy,
        )
        assert decision.allowed
    """

    def __init__(self) -> None:
        # Simple in-memory rate limiter: domain -> list of timestamps
        self._request_log: dict[str, list[float]] = {}

    def evaluate_request(
        self,
        request: NetworkRequest,
        policy: WorldNetworkPolicy,
    ) -> NetworkDecision:
        """Evaluate a network request against the world's policy.

        Evaluation order (C7 §22):
          1. Mode check (OFFLINE → deny all)
          2. Blocked domain check
          3. Allowed domain check (for RESTRICTED/CONTROLLED)
          4. Port check
          5. Rate limit check
        """
        domain = self._extract_domain(request.url)
        mode = policy.mode

        # 1. OFFLINE mode — deny everything
        if mode == NetworkMode.OFFLINE:
            return NetworkDecision(
                allowed=False,
                reason="World is in OFFLINE mode. No network access.",
                domain=domain,
                mode=mode.value,
            )

        # 2. Blocked domain check
        if self._is_blocked(domain, policy.blocked_domains):
            logger.warning(
                "network_request_blocked",
                domain=domain,
                url=request.url,
                world_instance=request.world_instance_id,
            )
            return NetworkDecision(
                allowed=False,
                reason=f"Domain '{domain}' is blocked by world policy.",
                domain=domain,
                mode=mode.value,
            )

        # 3. Allowed domain check (RESTRICTED and CONTROLLED modes)
        if mode in (NetworkMode.RESTRICTED, NetworkMode.CONTROLLED):
            if policy.allowed_domains and not self._is_allowed(
                domain, policy.allowed_domains,
            ):
                logger.warning(
                    "network_request_not_allowed",
                    domain=domain,
                    url=request.url,
                    world_instance=request.world_instance_id,
                )
                return NetworkDecision(
                    allowed=False,
                    reason=(
                        f"Domain '{domain}' is not in the allowed list. "
                        f"Allowed: {policy.allowed_domains[:5]}"
                    ),
                    domain=domain,
                    mode=mode.value,
                )

        # 4. Port check
        port = self._extract_port(request.url)
        if port and policy.allowed_ports and port not in policy.allowed_ports:
            return NetworkDecision(
                allowed=False,
                reason=f"Port {port} is not allowed. Allowed: {policy.allowed_ports}",
                domain=domain,
                mode=mode.value,
            )

        # 5. Rate limit check
        if mode in (NetworkMode.CONTROLLED, NetworkMode.RESTRICTED):
            if self._is_rate_limited(domain, policy.rate_limit_per_minute):
                return NetworkDecision(
                    allowed=False,
                    reason=f"Rate limit exceeded for domain '{domain}'.",
                    domain=domain,
                    mode=mode.value,
                    rate_limited=True,
                )

        # 6. Log the request (CONTROLLED mode)
        if mode == NetworkMode.CONTROLLED and policy.log_all_requests:
            self._log_request(domain)

        # 7. Proxy check
        if mode == NetworkMode.PROXY and not policy.proxy_url:
            return NetworkDecision(
                allowed=False,
                reason="PROXY mode requires a proxy_url configuration.",
                domain=domain,
                mode=mode.value,
            )

        return NetworkDecision(
            allowed=True,
            reason="Request allowed by network policy.",
            domain=domain,
            mode=mode.value,
        )

    def evaluate_batch(
        self,
        requests: list[NetworkRequest],
        policy: WorldNetworkPolicy,
    ) -> list[NetworkDecision]:
        """Evaluate multiple requests against the same policy."""
        return [self.evaluate_request(r, policy) for r in requests]

    def get_request_count(
        self, domain: str, window_seconds: int = 60,
    ) -> int:
        """Get the number of requests to a domain within a time window."""
        now = time.time()
        cutoff = now - window_seconds
        timestamps = self._request_log.get(domain, [])
        return sum(1 for t in timestamps if t >= cutoff)

    def reset_rate_limits(self) -> None:
        """Clear all rate limit counters."""
        self._request_log.clear()

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract the domain from a URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.hostname or ""
        except Exception:
            return ""

    @staticmethod
    def _extract_port(url: str) -> int | None:
        """Extract the port from a URL, if explicitly specified."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.port
        except Exception:
            return None

    @staticmethod
    def _is_allowed(domain: str, allowed_list: list[str]) -> bool:
        """Check if a domain matches the allowed list (supports wildcards)."""
        if not domain:
            return False
        for allowed in allowed_list:
            if allowed.startswith("*."):
                # Wildcard: *.example.com matches sub.example.com
                suffix = allowed[1:]  # .example.com
                if domain.endswith(suffix) or domain == allowed[2:]:
                    return True
            elif domain == allowed:
                return True
        return False

    @staticmethod
    def _is_blocked(domain: str, blocked_list: list[str]) -> bool:
        """Check if a domain is in the blocked list."""
        if not domain:
            return False
        for blocked in blocked_list:
            if blocked.startswith("*."):
                suffix = blocked[1:]
                if domain.endswith(suffix) or domain == blocked[2:]:
                    return True
            elif domain == blocked:
                return True
        return False

    def _is_rate_limited(
        self, domain: str, max_per_minute: int,
    ) -> bool:
        """Check if a domain has exceeded the rate limit."""
        if max_per_minute <= 0:
            return False
        count = self.get_request_count(domain, window_seconds=60)
        return count >= max_per_minute

    def _log_request(self, domain: str) -> None:
        """Record a request timestamp for rate limiting."""
        if domain not in self._request_log:
            self._request_log[domain] = []
        self._request_log[domain].append(time.time())

        # Prune old entries (older than 2 minutes)
        cutoff = time.time() - 120
        self._request_log[domain] = [
            t for t in self._request_log[domain] if t >= cutoff
        ]