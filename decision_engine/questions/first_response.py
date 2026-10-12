"""Manual first-response questions; the frozen replay question set stays unchanged."""

from decision_engine.questions.catalog import questions as replay_questions

VERSION = "first-response-v1"
REASONS = {
    "database_connectivity": "Database connection unavailable or failing",
    "database_pressure": "Database connections, pool waits or locking under pressure",
    "cache_or_event_connectivity": "Redis cache or event transport unavailable",
    "asynchronous_processing_delay": "Consumer or relay processing delayed",
    "business_or_validation_rejection": "Request validation or expected business rejection",
    "application_error": "Application request handling failed",
    "transport_or_deadline": "A request or dependency exceeded its deadline",
    "no_observed_failure": "No failure demonstrated in the supplied observations",
    "insufficient_evidence": "Evidence missing, stale or contradictory; cause unknown",
}


def questions(actions=None):
    result = replay_questions(actions)
    result["likely_reason"] = {
        "type": "choice",
        "instructions": "Suggest the best-supported possible reason for the operator's call problem. Request evidence is specific to the call; current metrics are a separate time window. Operator-reported symptoms are unverified. This is a hypothesis, never a confirmed injected cause. Choose insufficient_evidence when no reason is supported.",
        "criteria": REASONS.copy(),
    }
    return result
