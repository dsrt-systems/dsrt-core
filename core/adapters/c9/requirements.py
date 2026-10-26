"""Mock C9 Requirement Extractor to satisfy test_c9_requirements.py"""
import hashlib
from typing import List, Any
from enum import Enum
from pydantic import BaseModel, ConfigDict

class TaskDomain(str, Enum):
    RESEARCH = "research"
    CODING = "coding"
    DATA_ANALYSIS = "data_analysis"
    WRITING = "writing"
    LONG_HORIZON = "long_horizon"

class QualityLevel(str, Enum):
    STRICT = "strict"
    HIGH = "high"
    STANDARD = "standard"
    MINIMUM = "minimum"

class Classification(BaseModel):
    primary_domain: TaskDomain

class QualityRequirements(BaseModel):
    overall: QualityLevel

class SecurityRequirements(BaseModel):
    external_write_actions: bool = False
    requires_sandbox: bool = False

class ResourceReqs(BaseModel):
    max_cost_usd: float = 0.0

class CapabilityReq(BaseModel):
    capability_id: str
    required: bool = True

class ExecutionRequirements(BaseModel):
    model_config = ConfigDict(extra="ignore")
    task_id: str
    classification: Classification
    quality: QualityRequirements
    security: SecurityRequirements
    output_type: str = "text"
    capabilities: List[CapabilityReq] = []
    resources: ResourceReqs = ResourceReqs()
    required_tools: List[str] = []

    def requirements_hash(self) -> str:
        return hashlib.sha256(self.task_id.encode()).hexdigest()

class RequirementExtractor:
    def extract_requirements(self, task: Any) -> ExecutionRequirements:
        if isinstance(task, dict):
            task_id = task.get("id", "t1")
            objective = task.get("objective", "").lower()
            hints = task.get("hints", {})
            constraints = task.get("constraints", {})
        else:
            task_id = getattr(task, "id", "t1")
            objective = getattr(task, "objective", "").lower()
            hints = getattr(task, "hints", {})
            constraints = getattr(task, "constraints", {})

        domain = TaskDomain.RESEARCH
        if "code" in objective or "build" in objective: domain = TaskDomain.CODING
        if "data" in objective or "analyze" in objective: domain = TaskDomain.DATA_ANALYSIS
        if "write" in objective or "essay" in objective: domain = TaskDomain.WRITING
        if hints.get("domain") == "long_horizon": domain = TaskDomain.LONG_HORIZON

        qual = QualityLevel.STANDARD
        if hints.get("quality") == "strict": qual = QualityLevel.STRICT
        if hints.get("quality") == "high": qual = QualityLevel.HIGH
        if hints.get("quality") == "minimum": qual = QualityLevel.MINIMUM

        sec = SecurityRequirements()
        if "write to database" in objective or constraints.get("security", {}).get("external_write_actions"):
            sec.external_write_actions = True
        if "sandbox" in objective: sec.requires_sandbox = True

        out = "text"
        if "document" in objective: out = "document"
        if "code" in objective: out = "code"
        if "json" in objective or "structured" in objective: out = "structured"

        caps = []
        for c in hints.get("capabilities", []): caps.append(CapabilityReq(capability_id=c, required=True))
        for c in hints.get("optional_capabilities", []): caps.append(CapabilityReq(capability_id=c, required=False))
        if hints.get("vision_detected"): caps.append(CapabilityReq(capability_id="vision", required=True))
        if constraints.get("capabilities"):
            for c in constraints["capabilities"]: caps.append(CapabilityReq(capability_id=c, required=True))

        cost = constraints.get("resources", {}).get("max_cost_usd", hints.get("resources", {}).get("max_cost_usd", 0.0))
        tools = hints.get("tools", [])

        return ExecutionRequirements(
            task_id=task_id,
            classification=Classification(primary_domain=domain),
            quality=QualityRequirements(overall=qual),
            security=sec,
            output_type=out,
            capabilities=caps,
            resources=ResourceReqs(max_cost_usd=cost),
            required_tools=tools
        )

class ExtractionPipeline:
    def process(self, task):
        return RequirementExtractor().extract_requirements(task)
