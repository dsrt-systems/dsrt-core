"""
Phase C11.3: Adaptive Model Selection Module
"""

from core.optimization.model_selection.selector import AdaptiveModelSelector
from core.optimization.model_selection.policy import SelectionPolicyEvaluator
from core.optimization.model_selection.substitution import ModelSubstitutionEngine

__all__ = [
    "AdaptiveModelSelector",
    "SelectionPolicyEvaluator",
    "ModelSubstitutionEngine",
]