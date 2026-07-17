"""Service layer: detection, agent reasoning, planograms, auth, and storage."""

from app.services.agent import RetailAgent, get_agent
from app.services.auth import AuthUser, authenticate_user, get_current_user, get_optional_user
from app.services.closed_loop import ClosedLoopAgent, get_closed_loop_agent, reset_closed_loop_agent
from app.services.detector import GapDetector, GapDetectionResult, get_detector, reset_detector
from app.services.planogram_match import match_planogram
from app.services.planogram_store import PlanogramStore, get_planogram_store, reset_planogram_store
from app.services.store import RecordStore, get_store, reset_store
from app.services.ticket_store import TicketStore, get_ticket_store, reset_ticket_store

__all__ = [
    "RetailAgent",
    "get_agent",
    "ClosedLoopAgent",
    "get_closed_loop_agent",
    "reset_closed_loop_agent",
    "AuthUser",
    "authenticate_user",
    "get_current_user",
    "get_optional_user",
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
    "reset_store",
    "TicketStore",
    "get_ticket_store",
    "reset_ticket_store",
]
