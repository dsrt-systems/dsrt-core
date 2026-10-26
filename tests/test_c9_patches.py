import pytest
from core.adapters.c9.requirements import RequirementExtractor, TaskDomain

def hook_test_custom_id():
    req = RequirementExtractor().extract_requirements({"id": "custom_123", "objective": "test"})
    assert req.task_id == "custom_123"
