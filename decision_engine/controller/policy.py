from decision_engine.questions.catalog import TOOLS

VERSION = "shadow-policy-v1"
NOUL_THRESHOLD = 0.5  # Evidence collection preference only; uncalibrated, no execution authority.


def impaired(s):
    return (
        s["database"].get("reachable") is False
        or s["redis"].get("reachable") is False
        or (s["api"].get("error_rate_pct") or 0) >= 5
        or (s["worker"].get("outbox_oldest_seconds") or 0) >= 10
    )


def detected(history):
    return len(history) >= 2 and all(impaired(s) for s in history[-2:])


def baseline(s):
    """Frozen rules consume the same causal snapshot as Laya, never labels."""
    if s["integrity"]["status"] == "FAIL":
        return {"subsystem": "unknown", "tool": "escalate"}
    if (
        s["database"].get("reachable") is False
        or (s["database"].get("connection_usage_pct") or 0) >= 85
        or (s["database"].get("lock_waits") or 0) > 0
    ):
        return {"subsystem": "postgres", "tool": "inspect_database"}
    if s["redis"].get("reachable") is False:
        return {"subsystem": "redis", "tool": "inspect_redis"}
    if (s["worker"].get("outbox_oldest_seconds") or 0) >= 10 or (
        s["worker"].get("consumer_lag_messages") or 0
    ) > 10:
        return {"subsystem": "worker", "tool": "inspect_worker"}
    if (s["api"].get("error_rate_pct") or 0) >= 5:
        return {"subsystem": "api", "tool": "inspect_api"}
    return {"subsystem": "unknown", "tool": "collect_more_evidence"}


def authorize(tool, state, *, step, mode, previous=None, changed=True):
    verdict, selected, reason = "ALLOW_READ_ONLY", tool, None
    if tool not in TOOLS:
        verdict, selected, reason = "REJECT", "escalate", "UNREGISTERED_TOOL"
    elif mode != "shadow":
        verdict, selected, reason = "REJECT", "escalate", "READONLY_READINESS_NOT_GRANTED"
    elif step >= 8 or state["integrity"]["status"] == "FAIL":
        verdict, selected, reason = "ESCALATE", "escalate", "BUDGET_OR_INTEGRITY"
    elif (
        state["integrity"]["status"] in ("UNKNOWN", "STALE")
        or state.get("source_quality", {}).get("dependencies") != "FRESH"
    ):
        verdict, selected, reason = (
            "DEFER_FOR_DATA",
            "collect_more_evidence",
            "CRITICAL_EVIDENCE_UNAVAILABLE",
        )
    elif previous == tool and not changed:
        verdict, selected, reason = "ABSTAIN", "escalate", "REPEAT_WITHOUT_NEW_EVIDENCE"
    elif tool == "escalate":
        verdict = "ESCALATE"
    return {
        "proposed": tool,
        "selected": selected,
        "verdict": verdict,
        "execute": False,
        "override_reason": reason,
        "policy_version": VERSION,
        "mode": mode,
    }
