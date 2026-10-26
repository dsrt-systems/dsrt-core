# tests/test_c9_requirements.py
"""
C9.3 — Requirement Extractor, Task Classifier, Capability Matcher.

Tests the complete requirement extraction pipeline:
  description → classification → capabilities → constraints → TaskRequirements
"""

import pytest

from core.routing.analyzer.classifier import TaskClassifier
from core.routing.capabilities.matcher import CapabilityMatcher
from core.routing.contracts import (
    AgentCapabilityEntry,
    AgentCapabilityProfile,
    CapabilityRequirement,
    ModelCapabilityEntry,
    ModelCapabilityProfile,
    ModelLimits,
    QualityRequirements,
    ResourceConstraints,
    SecurityRequirements,
    TaskClassification,
    TaskRequirements,
)
from core.routing.enums import (
    CapabilityImportance,
    ModelCapabilityType,
    ProficiencyLevel,
    QualityLevel,
    TaskDomain,
)
from core.routing.requirements.extractor import RequirementExtractor


# ════════════════════════════════════════════════════════════════════
# REQUIREMENT EXTRACTOR TESTS
# ════════════════════════════════════════════════════════════════════


class TestRequirementExtractor:

    def setup_method(self):
        self.extractor = RequirementExtractor()

    # ── Basic extraction ──────────────────────────────────────────

    def test_extract_minimal(self):
        reqs = self.extractor.extract(
            task_id="t1",
            description="Do something",
        )
        assert reqs.task_id == "t1"
        assert reqs.description == "Do something"
        assert isinstance(reqs.classification, TaskClassification)
        assert isinstance(reqs.quality, QualityRequirements)
        assert isinstance(reqs.resources, ResourceConstraints)
        assert isinstance(reqs.security, SecurityRequirements)

    def test_extract_research_task(self):
        reqs = self.extractor.extract(
            task_id="t2",
            description="Research this company and produce a detailed evidence-backed report",
        )
        assert reqs.classification.primary_domain == TaskDomain.RESEARCH
        cap_ids = [c.capability_id for c in reqs.capabilities]
        assert "web_research" in cap_ids
        assert "report_generation" in cap_ids
        assert "evidence_synthesis" in cap_ids

    def test_extract_coding_task(self):
        reqs = self.extractor.extract(
            task_id="t3",
            description="Write a Python function to implement a REST API endpoint",
        )
        assert reqs.classification.primary_domain == TaskDomain.CODING
        cap_ids = [c.capability_id for c in reqs.capabilities]
        assert "code_generation" in cap_ids

    def test_extract_data_task(self):
        reqs = self.extractor.extract(
            task_id="t4",
            description="Analyze this CSV dataset and create a chart showing trends",
        )
        assert reqs.classification.primary_domain == TaskDomain.DATA_ANALYSIS
        cap_ids = [c.capability_id for c in reqs.capabilities]
        assert "data_analysis" in cap_ids

    def test_extract_writing_task(self):
        reqs = self.extractor.extract(
            task_id="t5",
            description="Write a blog article about AI trends",
        )
        assert reqs.classification.primary_domain == TaskDomain.WRITING

    # ── Quality inference ─────────────────────────────────────────

    def test_quality_strict(self):
        reqs = self.extractor.extract(
            task_id="t6",
            description="Produce a strict verified report",
        )
        assert reqs.quality.overall == QualityLevel.STRICT

    def test_quality_high(self):
        reqs = self.extractor.extract(
            task_id="t7",
            description="Create a high quality verified analysis",
        )
        assert reqs.quality.overall == QualityLevel.HIGH

    def test_quality_minimum(self):
        reqs = self.extractor.extract(
            task_id="t8",
            description="Quick minimum summary",
        )
        assert reqs.quality.overall == QualityLevel.MINIMUM

    def test_quality_default(self):
        reqs = self.extractor.extract(
            task_id="t9",
            description="Do a thing",
        )
        assert reqs.quality.overall == QualityLevel.STANDARD

    # ── Security inference ────────────────────────────────────────

    def test_security_no_write(self):
        reqs = self.extractor.extract(
            task_id="t10",
            description="Research this topic",
        )
        assert reqs.security.external_write_actions is False

    def test_security_write_detected(self):
        reqs = self.extractor.extract(
            task_id="t11",
            description="Send email to the team with the report",
        )
        assert reqs.security.external_write_actions is True

    def test_security_sandbox_detected(self):
        reqs = self.extractor.extract(
            task_id="t12",
            description="Execute code to process the data",
        )
        assert reqs.security.requires_sandbox is True

    # ── Output type inference ─────────────────────────────────────

    def test_output_document(self):
        reqs = self.extractor.extract(
            task_id="t13",
            description="Generate a report",
        )
        assert reqs.output_type == "document"

    def test_output_code(self):
        reqs = self.extractor.extract(
            task_id="t14",
            description="Write a function",
        )
        assert reqs.output_type == "code"

    def test_output_structured(self):
        reqs = self.extractor.extract(
            task_id="t15",
            description="Return the results as json",
        )
        assert reqs.output_type == "structured"

    def test_output_text_default(self):
        reqs = self.extractor.extract(
            task_id="t16",
            description="Tell me about cats",
        )
        assert reqs.output_type == "text"

    # ── Explicit overrides ────────────────────────────────────────

    def test_explicit_classification(self):
        explicit = TaskClassification(
            primary_domain=TaskDomain.LONG_HORIZON,
        )
        reqs = self.extractor.extract(
            task_id="t17",
            description="Research this topic",
            explicit_classification=explicit,
        )
        assert reqs.classification.primary_domain == TaskDomain.LONG_HORIZON

    def test_explicit_capabilities(self):
        caps = [
            CapabilityRequirement(capability_id="custom_cap"),
        ]
        reqs = self.extractor.extract(
            task_id="t18",
            description="Do something",
            explicit_capabilities=caps,
        )
        assert len(reqs.capabilities) == 1
        assert reqs.capabilities[0].capability_id == "custom_cap"

    def test_explicit_resources(self):
        res = ResourceConstraints(max_cost_usd=5.0, max_duration_seconds=600)
        reqs = self.extractor.extract(
            task_id="t19",
            description="Do something",
            explicit_resources=res,
        )
        assert reqs.resources.max_cost_usd == 5.0

    def test_explicit_security(self):
        sec = SecurityRequirements(
            external_write_actions=True,
            requires_sandbox=True,
        )
        reqs = self.extractor.extract(
            task_id="t20",
            description="Research this",
            explicit_security=sec,
        )
        assert reqs.security.external_write_actions is True
        assert reqs.security.requires_sandbox is True

    # ── Hints ─────────────────────────────────────────────────────

    def test_hints_capabilities(self):
        reqs = self.extractor.extract(
            task_id="t21",
            description="Do something",
            hints={"capabilities": ["custom_research", "custom_analysis"]},
        )
        cap_ids = [c.capability_id for c in reqs.capabilities]
        assert "custom_research" in cap_ids
        assert "custom_analysis" in cap_ids

    def test_hints_optional_capabilities(self):
        reqs = self.extractor.extract(
            task_id="t22",
            description="Do something",
            hints={"optional_capabilities": ["vision"]},
        )
        opt = [c for c in reqs.capabilities if not c.required]
        assert any(c.capability_id == "vision" for c in opt)

    def test_hints_resources(self):
        reqs = self.extractor.extract(
            task_id="t23",
            description="Do something",
            hints={"max_cost_usd": 3.0, "max_duration_seconds": 120},
        )
        assert reqs.resources.max_cost_usd == 3.0
        assert reqs.resources.max_duration_seconds == 120

    def test_hints_tools(self):
        reqs = self.extractor.extract(
            task_id="t24",
            description="Do something",
            required_tools=["web.search"],
            preferred_tools=["pdf.extract"],
        )
        assert reqs.required_tools == ["web.search"]
        assert reqs.preferred_tools == ["pdf.extract"]

    # ── Requirements hash ─────────────────────────────────────────

    def test_hash_is_deterministic(self):
        reqs = self.extractor.extract(
            task_id="t25",
            description="Research this company",
        )
        h1 = reqs.requirements_hash()
        h2 = reqs.requirements_hash()
        assert h1 == h2
        assert len(h1) == 64

    # ── Vision capability ─────────────────────────────────────────

    def test_vision_detected(self):
        reqs = self.extractor.extract(
            task_id="t26",
            description="Analyze this image and describe what you see",
        )
        cap_ids = [c.capability_id for c in reqs.capabilities]
        assert "vision" in cap_ids


# ════════════════════════════════════════════════════════════════════
# TASK CLASSIFIER TESTS
# ════════════════════════════════════════════════════════════════════


class TestTaskClassifier:

    def setup_method(self):
        self.classifier = TaskClassifier()

    def test_research_classification(self):
        result = self.classifier.classify(
            "Research the latest developments in quantum computing"
        )
        assert result.primary_domain == TaskDomain.RESEARCH
        assert result.confidence > 0.3

    def test_coding_classification(self):
        result = self.classifier.classify(
            "Implement a binary search tree in Python and write unit tests"
        )
        assert result.primary_domain == TaskDomain.CODING

    def test_data_analysis_classification(self):
        result = self.classifier.classify(
            "Analyze this CSV dataset and create statistics and a chart"
        )
        assert result.primary_domain == TaskDomain.DATA_ANALYSIS

    def test_writing_classification(self):
        result = self.classifier.classify(
            "Write a blog article about climate change"
        )
        assert result.primary_domain == TaskDomain.WRITING

    def test_planning_classification(self):
        result = self.classifier.classify(
            "Create a project roadmap and schedule with milestones"
        )
        assert result.primary_domain == TaskDomain.PLANNING

    def test_browser_classification(self):
        result = self.classifier.classify(
            "Browse the website and scrape the pricing data"
        )
        assert result.primary_domain == TaskDomain.BROWSER_OPERATION

    def test_document_classification(self):
        result = self.classifier.classify(
            "Extract text from this PDF document and parse the tables"
        )
        assert result.primary_domain == TaskDomain.DOCUMENT_PROCESSING

    def test_general_fallback(self):
        result = self.classifier.classify("Hello, how are you?")
        assert result.primary_domain == TaskDomain.GENERAL
        assert result.confidence == 0.5

    def test_multi_label(self):
        result = self.classifier.classify(
            "Research this company and write a detailed report with data analysis"
        )
        assert result.primary_domain == TaskDomain.RESEARCH
        # Should have secondary domains
        assert len(result.secondary_domains) >= 1

    def test_confidence_bounds(self):
        result = self.classifier.classify("Research and investigate and study")
        assert 0.0 <= result.confidence <= 1.0

    def test_long_horizon(self):
        result = self.classifier.classify(
            "Execute a multi-step complex workflow pipeline end-to-end"
        )
        assert result.primary_domain == TaskDomain.LONG_HORIZON

    def test_multi_agent(self):
        result = self.classifier.classify(
            "Orchestrate a multi-agent team to delegate tasks"
        )
        assert result.primary_domain == TaskDomain.MULTI_AGENT


# ════════════════════════════════════════════════════════════════════
# CAPABILITY MATCHER TESTS
# ════════════════════════════════════════════════════════════════════


class TestCapabilityMatcher:

    def setup_method(self):
        self.matcher = CapabilityMatcher()

    def _make_agent_profile(
        self, agent_id: str, capabilities: list[str]
    ) -> AgentCapabilityProfile:
        return AgentCapabilityProfile(
            agent_id=agent_id,
            agent_version_id=f"{agent_id}_v1",
            capabilities=[
                AgentCapabilityEntry(
                    capability_id=c,
                    proficiency=ProficiencyLevel.PRODUCTION,
                )
                for c in capabilities
            ],
        )

    def _make_model_profile(
        self,
        model_id: str,
        caps: list[ModelCapabilityType],
        context_tokens: int | None = None,
    ) -> ModelCapabilityProfile:
        return ModelCapabilityProfile(
            model_id=model_id,
            model_version_id=f"{model_id}_v1",
            provider_id="test_provider",
            capabilities=[
                ModelCapabilityEntry(capability=c) for c in caps
            ],
            limits=ModelLimits(context_tokens=context_tokens),
        )

    # ── Agent matching ────────────────────────────────────────────

    def test_agent_all_required_met(self):
        reqs = TaskRequirements(
            task_id="t1",
            description="Research task",
            capabilities=[
                CapabilityRequirement(capability_id="web_research"),
                CapabilityRequirement(capability_id="report_generation"),
            ],
        )
        profile = self._make_agent_profile(
            "research_agent", ["web_research", "report_generation", "citation"]
        )
        summary = self.matcher.match_agent(reqs, profile)
        assert summary.all_required_met
        assert summary.match_score == 1.0
        assert summary.missing_required == []

    def test_agent_missing_required(self):
        reqs = TaskRequirements(
            task_id="t2",
            description="Research task",
            capabilities=[
                CapabilityRequirement(capability_id="web_research"),
                CapabilityRequirement(capability_id="vision"),
            ],
        )
        profile = self._make_agent_profile(
            "text_agent", ["web_research", "writing"]
        )
        summary = self.matcher.match_agent(reqs, profile)
        assert not summary.all_required_met
        assert "vision" in summary.missing_required

    def test_agent_optional_missing_is_ok(self):
        reqs = TaskRequirements(
            task_id="t3",
            description="Task",
            capabilities=[
                CapabilityRequirement(capability_id="web_research"),
                CapabilityRequirement(
                    capability_id="vision",
                    required=False,
                    importance=CapabilityImportance.OPTIONAL,
                ),
            ],
        )
        profile = self._make_agent_profile("agent1", ["web_research"])
        summary = self.matcher.match_agent(reqs, profile)
        assert summary.all_required_met
        assert summary.match_score == 0.5  # 1 of 2 matched

    def test_agent_empty_requirements(self):
        reqs = TaskRequirements(task_id="t4", description="Simple task")
        profile = self._make_agent_profile("agent1", ["web_research"])
        summary = self.matcher.match_agent(reqs, profile)
        assert summary.all_required_met  # vacuously true
        assert summary.match_score == 0.0  # no requirements to match

    # ── Model matching ────────────────────────────────────────────

    def test_model_all_required_met(self):
        reqs = TaskRequirements(
            task_id="t5",
            description="Task",
            capabilities=[
                CapabilityRequirement(capability_id="reasoning"),
                CapabilityRequirement(capability_id="tool_use"),
            ],
        )
        profile = self._make_model_profile(
            "model_x",
            [ModelCapabilityType.REASONING, ModelCapabilityType.TOOL_USE],
        )
        summary = self.matcher.match_model(reqs, profile)
        assert summary.all_required_met

    def test_model_missing_vision(self):
        reqs = TaskRequirements(
            task_id="t6",
            description="Task",
            capabilities=[
                CapabilityRequirement(capability_id="vision"),
            ],
        )
        profile = self._make_model_profile(
            "text_model", [ModelCapabilityType.REASONING]
        )
        summary = self.matcher.match_model(reqs, profile)
        assert not summary.all_required_met
        assert "vision" in summary.missing_required

    def test_model_context_window_check(self):
        reqs = TaskRequirements(
            task_id="t7",
            description="Task",
            resources=ResourceConstraints(max_input_tokens=200000),
        )
        profile = self._make_model_profile(
            "small_model",
            [ModelCapabilityType.REASONING],
            context_tokens=128000,
        )
        summary = self.matcher.match_model(reqs, profile)
        assert not summary.all_required_met
        assert "context_window" in summary.missing_required

    def test_model_context_window_sufficient(self):
        reqs = TaskRequirements(
            task_id="t8",
            description="Task",
            resources=ResourceConstraints(max_input_tokens=100000),
        )
        profile = self._make_model_profile(
            "large_model",
            [ModelCapabilityType.REASONING],
            context_tokens=200000,
        )
        summary = self.matcher.match_model(reqs, profile)
        assert summary.all_required_met

    def test_model_non_model_capability_skipped_if_optional(self):
        """Agent-level capabilities (e.g. web_research) are not model
        capabilities. If optional, they should be skipped."""
        reqs = TaskRequirements(
            task_id="t9",
            description="Task",
            capabilities=[
                CapabilityRequirement(
                    capability_id="web_research",
                    required=False,
                    importance=CapabilityImportance.OPTIONAL,
                ),
            ],
        )
        profile = self._make_model_profile(
            "model_x", [ModelCapabilityType.REASONING]
        )
        summary = self.matcher.match_model(reqs, profile)
        assert summary.all_required_met  # no required model caps

    # ── Batch matching ────────────────────────────────────────────

    def test_filter_eligible_agents(self):
        reqs = TaskRequirements(
            task_id="t10",
            description="Task",
            capabilities=[
                CapabilityRequirement(capability_id="web_research"),
                CapabilityRequirement(capability_id="citation"),
            ],
        )
        profiles = [
            self._make_agent_profile("full_agent", ["web_research", "citation"]),
            self._make_agent_profile("partial_agent", ["web_research"]),
            self._make_agent_profile("other_agent", ["code_generation"]),
        ]
        eligible = self.matcher.filter_eligible_agents(reqs, profiles)
        assert len(eligible) == 1
        assert eligible[0].agent_id == "full_agent"

    def test_filter_eligible_models(self):
        reqs = TaskRequirements(
            task_id="t11",
            description="Task",
            capabilities=[
                CapabilityRequirement(capability_id="vision"),
                CapabilityRequirement(capability_id="tool_use"),
            ],
        )
        profiles = [
            self._make_model_profile(
                "vision_model",
                [ModelCapabilityType.VISION, ModelCapabilityType.TOOL_USE],
            ),
            self._make_model_profile(
                "text_model",
                [ModelCapabilityType.TOOL_USE],
            ),
        ]
        eligible = self.matcher.filter_eligible_models(reqs, profiles)
        assert len(eligible) == 1
        assert eligible[0].model_id == "vision_model"

    def test_match_agents_batch(self):
        reqs = TaskRequirements(
            task_id="t12",
            description="Task",
            capabilities=[
                CapabilityRequirement(capability_id="web_research"),
            ],
        )
        profiles = [
            self._make_agent_profile("a1", ["web_research"]),
            self._make_agent_profile("a2", ["coding"]),
        ]
        results = self.matcher.match_agents(reqs, profiles)
        assert len(results) == 2
        assert results[0].all_required_met
        assert not results[1].all_required_met

    def test_match_models_batch(self):
        reqs = TaskRequirements(
            task_id="t13",
            description="Task",
            capabilities=[
                CapabilityRequirement(capability_id="reasoning"),
            ],
        )
        profiles = [
            self._make_model_profile("m1", [ModelCapabilityType.REASONING]),
            self._make_model_profile("m2", [ModelCapabilityType.VISION]),
        ]
        results = self.matcher.match_models(reqs, profiles)
        assert len(results) == 2
        assert results[0].all_required_met
        assert not results[1].all_required_met

    # ── Version checking ──────────────────────────────────────────

    def test_agent_version_check_pass(self):
        reqs = TaskRequirements(
            task_id="t14",
            description="Task",
            capabilities=[
                CapabilityRequirement(
                    capability_id="web_research",
                    minimum_version="2.0",
                ),
            ],
        )
        profile = AgentCapabilityProfile(
            agent_id="a1",
            agent_version_id="v1",
            capabilities=[
                AgentCapabilityEntry(
                    capability_id="web_research",
                    proficiency=ProficiencyLevel.PRODUCTION,
                    version="2.1",
                ),
            ],
        )
        summary = self.matcher.match_agent(reqs, profile)
        assert summary.all_required_met

    def test_agent_version_check_fail(self):
        reqs = TaskRequirements(
            task_id="t15",
            description="Task",
            capabilities=[
                CapabilityRequirement(
                    capability_id="web_research",
                    minimum_version="3.0",
                ),
            ],
        )
        profile = AgentCapabilityProfile(
            agent_id="a1",
            agent_version_id="v1",
            capabilities=[
                AgentCapabilityEntry(
                    capability_id="web_research",
                    proficiency=ProficiencyLevel.PRODUCTION,
                    version="2.1",
                ),
            ],
        )
        summary = self.matcher.match_agent(reqs, profile)
        assert not summary.all_required_met


# ════════════════════════════════════════════════════════════════════
# INTEGRATION: EXTRACTOR → CLASSIFIER → MATCHER
# ════════════════════════════════════════════════════════════════════


class TestExtractionPipeline:
    """End-to-end: description → requirements → matching."""

    def test_research_pipeline(self):
        extractor = RequirementExtractor()
        matcher = CapabilityMatcher()

        # 1. Extract
        reqs = extractor.extract(
            task_id="pipeline_1",
            description="Research this company and produce a detailed evidence-backed report with citations",
        )

        # 2. Verify extraction
        assert reqs.classification.primary_domain == TaskDomain.RESEARCH
        assert len(reqs.required_capabilities) >= 3
        assert reqs.output_type == "document"

        # 3. Match against agents
        good_agent = AgentCapabilityProfile(
            agent_id="research_intelligence",
            agent_version_id="v1",
            capabilities=[
                AgentCapabilityEntry(capability_id=c, proficiency=ProficiencyLevel.PRODUCTION)
                for c in [
                    "web_research", "web_search", "source_analysis",
                    "evidence_synthesis", "citation", "report_generation",
                ]
            ],
        )
        bad_agent = AgentCapabilityProfile(
            agent_id="coding_agent",
            agent_version_id="v1",
            capabilities=[
                AgentCapabilityEntry(capability_id="code_generation", proficiency=ProficiencyLevel.PRODUCTION),
            ],
        )

        good_summary = matcher.match_agent(reqs, good_agent)
        bad_summary = matcher.match_agent(reqs, bad_agent)

        assert good_summary.all_required_met
        assert not bad_summary.all_required_met
        assert len(bad_summary.missing_required) > 0

    def test_coding_pipeline(self):
        extractor = RequirementExtractor()
        matcher = CapabilityMatcher()

        reqs = extractor.extract(
            task_id="pipeline_2",
            description="Implement a REST API with structured output as json",
        )

        assert reqs.classification.primary_domain == TaskDomain.CODING

        model = ModelCapabilityProfile(
            model_id="code_model",
            model_version_id="v1",
            provider_id="test",
            capabilities=[
                ModelCapabilityEntry(capability=ModelCapabilityType.CODE_GENERATION),
                ModelCapabilityEntry(capability=ModelCapabilityType.STRUCTURED_OUTPUT),
                ModelCapabilityEntry(capability=ModelCapabilityType.TOOL_USE),
            ],
        )
        summary = matcher.match_model(reqs, model)
        assert summary.all_required_met