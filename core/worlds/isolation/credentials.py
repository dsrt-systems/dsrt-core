"""
World Credential Broker (C7 §24-25).

Manages credential injection into World instances without exposing
secrets to agents.

Architecture (C7 §24):
    Agent → Tool Request
        ↓
    Credential Broker → Policy Check
        ↓
    Credential Injection → Tool
        ↓
    Agent receives result (NOT the secret)

Rules:
  - Agents receive 'credential://github/read' references
  - Secrets are never written to logs, events, memory, context, or artifacts
  - Credential access is audited
  - Cross-tenant credential access is denied
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.api.errors.exceptions import AuthorizationError, NotFoundError
from core.observability.logging import get_logger


logger = get_logger("dsrt.worlds.credentials")


@dataclass
class CredentialReference:
    """A safe credential reference that agents can use.

    Contains NO secret material — only the reference string
    and metadata about what it grants access to.
    """
    ref: str  # e.g., "credential://github/read"
    provider: str
    scope: str
    organization_id: str
    description: str = ""


@dataclass
class CredentialInjection:
    """Result of injecting a credential into a tool execution.

    The secret is included only for the tool runtime to use.
    It must NEVER be passed to the agent or logged.
    """
    credential_ref: str
    secret_value: str  # Only for tool runtime — NEVER log or expose
    provider: str
    scope: str
    injected_into: str = ""


class WorldCredentialBroker:
    """Manages credential access for World instances (C7 §24-25).

    Usage:
        broker = WorldCredentialBroker()

        # Register a credential for a world
        broker.register_credential(
            organization_id="org_1",
            world_instance_id="wi_1",
            provider="github",
            scope="read",
            secret="ghp_xxxx",  # Stored securely, never exposed
        )

        # Agent requests access via reference
        ref = broker.get_reference("org_1", "wi_1", "github", "read")
        # ref.ref == "credential://github/read"  (no secret!)

        # Tool runtime injects the actual secret
        injection = broker.inject("org_1", "wi_1", "credential://github/read")
        # injection.secret_value == "ghp_xxxx"  (only for tool, never agent)
    """

    def __init__(self) -> None:
        # In-memory credential store (production: use C2 CredentialManager + vault)
        # Key: (org_id, world_id, provider, scope) → secret
        self._store: dict[tuple[str, str, str, str], str] = {}
        # Audit log
        self._audit_log: list[dict[str, Any]] = []

    def register_credential(
        self,
        *,
        organization_id: str,
        world_instance_id: str,
        provider: str,
        scope: str,
        secret: str,
        description: str = "",
    ) -> CredentialReference:
        """Register a credential for a world instance.

        The secret is stored internally and never exposed through
        the reference object.
        """
        key = (organization_id, world_instance_id, provider, scope)
        self._store[key] = secret

        self._audit_log.append({
            "action": "REGISTER",
            "organization_id": organization_id,
            "world_instance_id": world_instance_id,
            "provider": provider,
            "scope": scope,
        })

        logger.info(
            "credential_registered",
            org=organization_id,
            world=world_instance_id,
            provider=provider,
            scope=scope,
        )

        return CredentialReference(
            ref=f"credential://{provider}/{scope}",
            provider=provider,
            scope=scope,
            organization_id=organization_id,
            description=description,
        )

    def get_reference(
        self,
        organization_id: str,
        world_instance_id: str,
        provider: str,
        scope: str,
    ) -> CredentialReference:
        """Get a safe credential reference (NO secret material).

        This is what agents receive — a reference string they can
        pass to tools, but which contains no actual secret.
        """
        key = (organization_id, world_instance_id, provider, scope)
        if key not in self._store:
            raise NotFoundError(
                f"Credential '{provider}/{scope}' not found "
                f"for world '{world_instance_id}'."
            )

        return CredentialReference(
            ref=f"credential://{provider}/{scope}",
            provider=provider,
            scope=scope,
            organization_id=organization_id,
        )

    def inject(
        self,
        organization_id: str,
        world_instance_id: str,
        credential_ref: str,
        target_component: str = "",
    ) -> CredentialInjection:
        """Inject a credential's secret into a tool execution.

        CRITICAL: The returned secret_value must ONLY be used by the
        tool runtime. It must NEVER be:
          - Passed to the agent
          - Written to logs
          - Stored in memory/context
          - Included in artifacts
          - Emitted in events
        """
        # Parse the credential reference
        provider, scope = self._parse_ref(credential_ref)

        # Tenant isolation check
        key = (organization_id, world_instance_id, provider, scope)
        if key not in self._store:
            raise NotFoundError(
                f"Credential '{credential_ref}' not found or "
                f"access denied for org '{organization_id}'."
            )

        secret = self._store[key]

        # Audit the injection
        self._audit_log.append({
            "action": "INJECT",
            "organization_id": organization_id,
            "world_instance_id": world_instance_id,
            "credential_ref": credential_ref,
            "target_component": target_component,
        })

        logger.info(
            "credential_injected",
            org=organization_id,
            world=world_instance_id,
            ref=credential_ref,
            target=target_component,
        )

        return CredentialInjection(
            credential_ref=credential_ref,
            secret_value=secret,
            provider=provider,
            scope=scope,
            injected_into=target_component,
        )

    def revoke(
        self,
        organization_id: str,
        world_instance_id: str,
        provider: str,
        scope: str,
    ) -> bool:
        """Revoke a credential from a world instance."""
        key = (organization_id, world_instance_id, provider, scope)
        if key in self._store:
            del self._store[key]
            self._audit_log.append({
                "action": "REVOKE",
                "organization_id": organization_id,
                "world_instance_id": world_instance_id,
                "provider": provider,
                "scope": scope,
            })
            logger.info(
                "credential_revoked",
                org=organization_id,
                world=world_instance_id,
                provider=provider,
            )
            return True
        return False

    def list_references(
        self,
        organization_id: str,
        world_instance_id: str,
    ) -> list[CredentialReference]:
        """List all credential references for a world (no secrets)."""
        refs: list[CredentialReference] = []
        for (org, wid, provider, scope) in self._store:
            if org == organization_id and wid == world_instance_id:
                refs.append(CredentialReference(
                    ref=f"credential://{provider}/{scope}",
                    provider=provider,
                    scope=scope,
                    organization_id=organization_id,
                ))
        return refs

    def get_audit_log(
        self,
        organization_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get the credential access audit log."""
        entries = self._audit_log
        if organization_id:
            entries = [
                e for e in entries
                if e.get("organization_id") == organization_id
            ]
        return entries[-limit:]

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_ref(credential_ref: str) -> tuple[str, str]:
        """Parse 'credential://provider/scope' into (provider, scope)."""
        if not credential_ref.startswith("credential://"):
            raise ValueError(
                f"Invalid credential reference: '{credential_ref}'. "
                f"Must start with 'credential://'."
            )
        parts = credential_ref[len("credential://"):].split("/", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid credential reference format: '{credential_ref}'. "
                f"Expected 'credential://provider/scope'."
            )
        return parts[0], parts[1]