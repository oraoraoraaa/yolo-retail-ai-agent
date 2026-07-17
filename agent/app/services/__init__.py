"""Service layer: detection, agent reasoning, planograms, and record storage."""

from app.services.agent import RetailAgent, get_agent
from app.services.detector import GapDetector, GapDetectionResult, get_detector, reset_detector
from app.services.planogram_match import match_planogram
from app.services.planogram_store import PlanogramStore, get_planogram_store, reset_planogram_store
from app.services.store import RecordStore, get_store

__all__ = [
    "RetailAgent",
    "get_agent",
    "GapDetector",
    "GapDetectionResult",
    "get_detector",
    "reset_detector",
    "PlanogramStore",
    "get_planogram_store",
    "reset_planogram_store",
    "match_planogram",
    "RecordStore",
    "get_store",
]
