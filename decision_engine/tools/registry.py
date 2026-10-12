"""Catalog only; executor intentionally absent until independent read-only GO."""

from decision_engine.questions.catalog import TOOLS


def catalog():
    return [
        {
            "tool_id": key,
            "description": desc,
            "input_schema": {"type": "object", "additionalProperties": False, "properties": {}},
            "timeout_seconds": 10,
            "status": "SHADOW_RECOMMENDATION_ONLY",
            "read_only": True,
            "execution_enabled": False,
            "source": "sanitized_observation" if key != "inspect_traces" else "NOT_CAPTURED",
        }
        for key, desc in TOOLS.items()
    ]


async def execute(tool_id, args):
    raise PermissionError("READONLY_READINESS_NOT_GRANTED")
