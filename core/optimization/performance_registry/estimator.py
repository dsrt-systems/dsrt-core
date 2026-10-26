"""
Phase C11.2: Bayesian / Empirical Performance Estimator

Computes expected performance metrics using Bayesian inference for sparse data
and empirical statistics for dense sample sets.
"""

import math
from typing import List
from schemas.domain.performance_intelligence import PerformanceEvidence, PerformanceMetrics


class PerformanceEstimator:
    """Estimates model performance metrics using Bayesian updating and empirical distributions."""

    # Bayesian Beta-Binomial prior parameters for reliability
    PRIOR_ALPHA_RELIABILITY = 2.0  # prior successes
    PRIOR_BETA_RELIABILITY = 1.0   # prior failures

    # Conservative default prior for quality when zero or few samples exist
    DEFAULT_PRIOR_QUALITY = 0.70
    PRIOR_QUALITY_WEIGHT = 3.0

    def estimate_metrics(self, evidence_list: List[PerformanceEvidence]) -> PerformanceMetrics:
        n = len(evidence_list)

        if n == 0:
            return PerformanceMetrics(
                quality_mean=self.DEFAULT_PRIOR_QUALITY,
                quality_std=0.1,
                reliability_rate=0.85,
                latency_p50_ms=1000.0,
                latency_p90_ms=2500.0,
                latency_p99_ms=5000.0,
                cost_mean_usd=0.01,
                token_efficiency=100000.0,
                sample_count=0,
                confidence_interval_low=0.50,
                confidence_interval_high=0.90,
            )

        # 1. Quality Estimation with Prior Smoothing
        qualities = [e.quality_score for e in evidence_list]
        q_sum = sum(qualities)
        quality_mean = (q_sum + self.DEFAULT_PRIOR_QUALITY * self.PRIOR_QUALITY_WEIGHT) / (n + self.PRIOR_QUALITY_WEIGHT)

        if n > 1:
            q_var = sum((q - quality_mean) ** 2 for q in qualities) / (n - 1)
            quality_std = math.sqrt(q_var)
        else:
            quality_std = 0.1

        # 95% Confidence Interval for Quality
        stderr = quality_std / math.sqrt(n) if n > 0 else 0.1
        ci_low = max(0.0, quality_mean - 1.96 * stderr)
        ci_high = min(1.0, quality_mean + 1.96 * stderr)

        # 2. Reliability Estimation via Beta-Binomial Updating
        successes = sum(1.0 for e in evidence_list if e.reliability_score >= 0.99)
        alpha_post = self.PRIOR_ALPHA_RELIABILITY + successes
        beta_post = self.PRIOR_BETA_RELIABILITY + (n - successes)
        reliability_rate = alpha_post / (alpha_post + beta_post)

        # 3. Latency Distribution Percentiles
        latencies = sorted([e.latency_ms for e in evidence_list])
        p50 = self._percentile(latencies, 0.50)
        p90 = self._percentile(latencies, 0.90)
        p99 = self._percentile(latencies, 0.99)

        # 4. Economics & Token Efficiency
        costs = [e.cost_usd for e in evidence_list]
        cost_mean = sum(costs) / n

        total_tokens = sum(e.output_tokens for e in evidence_list)
        total_cost = sum(costs)
        if total_cost > 0:
            token_efficiency = total_tokens / total_cost
        else:
            token_efficiency = 100000.0

        return PerformanceMetrics(
            quality_mean=round(quality_mean, 4),
            quality_std=round(quality_std, 4),
            reliability_rate=round(reliability_rate, 4),
            latency_p50_ms=round(p50, 2),
            latency_p90_ms=round(p90, 2),
            latency_p99_ms=round(p99, 2),
            cost_mean_usd=round(cost_mean, 6),
            token_efficiency=round(token_efficiency, 2),
            sample_count=n,
            confidence_interval_low=round(ci_low, 4),
            confidence_interval_high=round(ci_high, 4),
        )

    def _percentile(self, sorted_vals: List[float], pct: float) -> float:
        if not sorted_vals:
            return 0.0
        if len(sorted_vals) == 1:
            return sorted_vals[0]
        
        idx = (len(sorted_vals) - 1) * pct
        floor_idx = math.floor(idx)
        ceil_idx = math.ceil(idx)
        
        if floor_idx == ceil_idx:
            return sorted_vals[int(idx)]
        
        weight = idx - floor_idx
        return sorted_vals[floor_idx] * (1.0 - weight) + sorted_vals[ceil_idx] * weight