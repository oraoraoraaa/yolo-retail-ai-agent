"""Service layer: detection, agent reasoning, and record storage."""

from app.services.agent import RetailAgent, get_agent
from app.services.detector import GapDetector, GapDetectionResult, get_detector, reset_detector
from app.services.store import RecordStore, get_store

__all__ = [
    "RetailAgent",
    "get_agent",
    "GapDetector",
    "GapDetectionResult",
    "get_detector",
    "reset_detector",
    "RecordStore",
    "get_store",
]
