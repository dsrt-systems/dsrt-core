# core/routing/adaptive/stage_router.py
"""
C9 Stage Router (§34–35).

Maps execution stages to routing preferences, enabling different
models/configurations per stage within a single task.

Example:
  PLANNING     → reasoning model
  RETRIEVAL    → tool-efficient model
  SYNTHESIS    → quality model
  VERIFICATION → verification model
"""

from __future__ import annotations

from core.routing.contracts import (
    Route,
    StageRoutePreference,
    StageRoutingConfig,
)
from core.routing.enums import ExecutionStage


class StageRouter:
    """Resolves per-stage routing preferences (§34–35).

    Args:
        default_config: Default stage routing configuration.
    """

    DEFAULT_CONFIG = StageRoutingConfig(
        stages=[
            StageRoutePreference(
                stage=ExecutionStage.PLANNING,
                model_profile="reasoning",
            ),
            StageRoutePreference(
                stage=ExecutionStage.RETRIEVAL,
                model_profile="tool_efficiency",
            ),
            StageRoutePreference(
                stage=ExecutionStage.ANALYSIS,
                model_profile="reasoning",
            ),
            StageRoutePreference(
                stage=ExecutionStage.SYNTHESIS,
                model_profile="quality",
            ),
            StageRoutePreference(
                stage=ExecutionStage.VERIFICATION,
                model_profile="verification",
            ),
            StageRoutePreference(
                stage=ExecutionStage.FINALIZATION,
                model_profile="quality",
            ),
        ],
    )

    def __init__(
        self,
        config: StageRoutingConfig | None = None,
    ) -> None:
        self._config = config or self.DEFAULT_CONFIG

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_stage_preference(
        self,
        stage: ExecutionStage,
    ) -> StageRoutePreference | None:
        """Get the routing preference for a specific stage."""
        return self._config.get_stage_preference(stage)

    def get_model_profile(
        self,
        stage: ExecutionStage,
    ) -> str:
        """Get the model profile name for a stage.

        Returns ``"default"`` if no stage-specific preference exists.
        """
        pref = self.get_stage_preference(stage)
        return pref.model_profile if pref else "default"

    def get_override_model(
        self,
        stage: ExecutionStage,
    ) -> str | None:
        """Get an explicit model override for a stage, if any."""
        pref = self.get_stage_preference(stage)
        return pref.override_model_id if pref else None

    def needs_route_change(
        self,
        current_stage: ExecutionStage,
        next_stage: ExecutionStage,
    ) -> bool:
        """Check if transitioning between stages requires a route change."""
        current_profile = self.get_model_profile(current_stage)
        next_profile = self.get_model_profile(next_stage)
        return current_profile != next_profile

    def list_stages(self) -> list[ExecutionStage]:
        """List all configured stages in order."""
        return [s.stage for s in self._config.stages]