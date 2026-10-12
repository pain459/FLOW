"""Immutable development question set; model text never supplies authorization."""

VERSION = "investigation-v1"
TOOLS = {
    "inspect_api": "Read HTTP error rates and request latency evidence",
    "inspect_database": "Read database reachability, connections, locking and SQL failure evidence",
    "inspect_redis": "Read Redis availability and cache/event transport evidence",
    "inspect_worker": "Read consumer and outbox backlog evidence",
    "inspect_network": "Read already observed transport timeout evidence",
    "inspect_traces": "Read sanitized request path summaries when captured",
    "collect_more_evidence": "Obtain another bounded observation window",
    "escalate": "Abstain and request operator investigation",
}


def questions(actions=None):
    actions = list(TOOLS) if actions is None else actions
    if not actions or len(set(actions)) != len(actions) or set(actions) - set(TOOLS):
        raise ValueError("unauthorized question options")
    return {
        "suspected_subsystem": {
            "type": "choice",
            "instructions": "Which subsystem merits investigation based on the observed evidence? A suspicion is not a confirmed cause.",
            "criteria": {
                "postgres": "database connectivity, SQL errors, connections or lock waits",
                "redis": "cache connectivity or stream delivery",
                "api": "HTTP request handling, exceptions and timeouts",
                "worker": "consumer or relay blocked, asynchronous backlog",
                "network": "transport impairment supported by measurements",
                "unknown": "insufficient or contradictory evidence",
            },
        },
        "incident_severity": {
            "type": "score",
            "instructions": "Rate severity of the observed operational impairment.",
            "criteria": ["none", "minor", "moderate", "major", "critical"],
        },
        "needs_more_evidence": {
            "type": "noul",
            "instructions": "Is evidence insufficient for a defensible diagnosis?",
        },
        "next_diagnostic_tool": {
            "type": "choice",
            "instructions": "Which approved read-only investigation could add useful evidence? Escalate if insufficient observations exist.",
            "criteria": {k: TOOLS[k] for k in actions},
        },
    }
