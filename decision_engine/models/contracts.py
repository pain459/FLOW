"""Project-owned normalization for the verified Laya 0.4.3 wire shape."""

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Budgets(StrictModel):
    decisions: int = Field(default=8, ge=1, le=8)
    tool_calls: int = Field(default=6, ge=0, le=6)
    deadline_seconds: int = Field(default=180, ge=1, le=180)
    inference_seconds: int = Field(default=15, ge=1, le=15)
    tool_seconds: int = Field(default=10, ge=1, le=10)


def probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("probability must be numeric")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("probability outside range")
    return float(value)


def validate_provider_result(
    value: dict, *, allow_fixture=False, question_version="investigation-v1"
) -> None:
    if not isinstance(value, dict) or set(value) - {
        "answers",
        "raw_answers",
        "question_version",
        "provider_version",
        "checkpoint_revision",
        "inference_ms",
        "input_quality",
    }:
        raise ValueError("unregistered provider fields")
    expected = {"laya-0.4.3"}
    if allow_fixture:
        expected.add("mock-fixture-v1")
    if value.get("provider_version") not in expected:
        raise ValueError("provider version not qualified")
    latency = value.get("inference_ms")
    if (
        isinstance(latency, bool)
        or not isinstance(latency, (int, float))
        or not math.isfinite(latency)
        or latency < 0
    ):
        raise ValueError("invalid inference latency")
    if value["provider_version"] == "laya-0.4.3" and (
        value.get("question_version") != question_version
        or value.get("checkpoint_revision") != "e4e9ddf21a7b1903b7acffd8814ad4307bf63a67"
    ):
        raise ValueError("provider question/checkpoint revision mismatch")
    if value["provider_version"] == "laya-0.4.3" and question_version == "first-response-v1":
        from decision_engine.inference_input import validate_quality

        validate_quality(value.get("input_quality"))


def normalize_answers(raw: dict, questions: dict) -> dict:
    answers = raw.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError("answer set differs from requested questions")
    normalized = {}
    allowed = {
        "type",
        "choice",
        "score",
        "noul",
        "probabilities",
        "legend",
        "confidence",
        "answer_confidence",
        "action",
        "x_jev_confidence",
    }
    for key, question in questions.items():
        a = answers[key]
        if not isinstance(a, dict) or set(a) - allowed or a.get("type") != question["type"]:
            raise ValueError("unexpected answer fields or type")
        result = {
            "type": a["type"],
            "confidence": probability(a["confidence"]),
            "answer_confidence": probability(a["answer_confidence"]),
        }
        action = a.get("action", {})
        if not isinstance(action, dict) or set(action) != {"act_probability"}:
            raise ValueError("invalid action head")
        result["act_probability"] = probability(action["act_probability"])
        if "x_jev_confidence" in a:
            result["x_jev_confidence"] = probability(a["x_jev_confidence"])
        if a["type"] == "noul":
            if any(x in a for x in ("choice", "score", "legend", "probabilities")):
                raise ValueError("conflicting noul fields")
            result["noul"] = probability(a["noul"])
        else:
            expected = (
                set(question["criteria"])
                if a["type"] == "choice"
                else {str(i) for i in range(len(question["criteria"]))}
            )
            p = a.get("probabilities")
            if not isinstance(p, dict) or set(p) != expected:
                raise ValueError("probability options differ")
            distribution = {k: probability(v) for k, v in p.items()}
            if abs(sum(distribution.values()) - 1) > 0.002:
                raise ValueError("distribution does not sum to one")
            if abs(max(distribution.values()) - result["answer_confidence"]) > 0.002:
                raise ValueError("answer confidence contradicts distribution")
            result["probabilities"] = distribution
            if a["type"] == "choice":
                if a.get("choice") not in expected or any(
                    x in a for x in ("noul", "score", "legend")
                ):
                    raise ValueError("unknown choice")
                if distribution[a["choice"]] < max(distribution.values()) - 0.002:
                    raise ValueError("choice contradicts distribution")
                result["choice"] = a["choice"]
            else:
                if "choice" in a or "noul" in a:
                    raise ValueError("conflicting score fields")
                legend = {str(i): v for i, v in enumerate(question["criteria"])}
                score = a.get("score")
                if (
                    isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not math.isfinite(score)
                ):
                    raise ValueError("invalid expected ordinal")
                if (
                    a.get("legend") != legend
                    or abs(score - sum(int(k) * v for k, v in distribution.items())) > 0.002
                ):
                    raise ValueError("ordinal mean/legend contradicts distribution")
                result.update(
                    score=score,
                    legend=legend,
                    most_likely_level=legend[max(distribution, key=distribution.get)],
                )
        normalized[key] = result
    return normalized
