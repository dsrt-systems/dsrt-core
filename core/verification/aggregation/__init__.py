"""
Verification Aggregation & Policy Engine (C6 §31-32, §45-46).

Policy-driven aggregation of verification check results into
final verification verdicts. Never majority-vote.
"""

from core.verification.aggregation.aggregator import VerificationAggregator
from core.verification.aggregation.rules import AggregationRule, RuleAction

__all__ = ["AggregationRule", "RuleAction", "VerificationAggregator"]