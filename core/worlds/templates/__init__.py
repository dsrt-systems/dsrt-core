"""
World Templates (C7 §49).

Pre-built world configurations for common use cases.
Templates provide a starting manifest that can be customized
per execution.
"""

from core.worlds.templates.software_world import SOFTWARE_WORLD_MANIFEST
from core.worlds.templates.data_science_world import DATA_SCIENCE_WORLD_MANIFEST
from core.worlds.templates.research_world_v2 import RESEARCH_WORLD_V2_MANIFEST

__all__ = [
    "DATA_SCIENCE_WORLD_MANIFEST",
    "RESEARCH_WORLD_V2_MANIFEST",
    "SOFTWARE_WORLD_MANIFEST",
]