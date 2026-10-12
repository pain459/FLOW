import asyncio
import hashlib
import json
import time
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

from decision_engine.adapters.datasets import load
from decision_engine.controller.policy import VERSION, authorize, baseline, detected
from decision_engine.models.contracts import Budgets, normalize_answers, validate_provider_result
from decision_engine.questions.catalog import questions, TOOLS, VERSION as QUESTION_VERSION
from decision_engine.adapters.live_evidence import LiveEvidenceClient
from decision_engine.adapters.calls import CallEvidenceClient
from decision_engine.models.live import Lookup, user_evidence
from decision_engine.questions.first_response import (
    questions as live_questions,
    VERSION as LIVE_QUESTION_VERSION,
)


def hash_payload(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()


def validate_sequence(states):
    stamps = [datetime.fromisoformat(s["observed_at"].replace("Z", "+00:00")) for s in states]
    if any(stamp.tzinfo is None for stamp in stamps) or any(
        b <= a for a, b in zip(stamps, stamps[1:])
    ):
        raise ValueError("replay requires strictly increasing UTC observations")


def replay_start(states):
    # Consume observations in order; no later observation selects an earlier action.
    # An incident starts only once two windows have confirmed the frozen condition.
    for index in range(len(states)):
        if detected(states[: index + 1]):
            return {"start_index": index, "triggered": True, "version": "sustained-observation-v1"}
    return {"start_index": 0, "triggered": False, "version": "sustained-observation-v1"}


class Controller:
    def __init__(self, store, provider, reports, *, allow_fixture=False):
        self.store, self.provider, self.reports = store, provider, reports
        self.allow_fixture = allow_fixture
        reports.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=reports):
            pass
        self.tasks = {}
        self.sources = {}
        self.plans = {}
        self.cancellations = {}
        self.live_collector = LiveEvidenceClient()
        self.call_collector = CallEvidenceClient()
        self.call_admission = asyncio.Lock()

    async def start(self, dataset, requester, key, budget=None):
        budget = budget or Budgets()
        states, source_hash = load(dataset)
        validate_sequence(states)
        request_hash = hash_payload({"dataset": dataset, "budget": budget.model_dump()})
        uid, created = await self.create(dataset, requester, key, budget, request_hash, "shadow")
        if created:
            self.sources[uid] = source_hash
            self.plans[uid] = replay_start(states)
            self.tasks[uid] = asyncio.create_task(self.run(uid, states, source_hash, budget))
        return uid

    async def start_live(self, body, requester, key):
        budget = Budgets(decisions=1, tool_calls=0, deadline_seconds=30)
        request_hash = hash_payload(
            {"kind": "live_question", "request": body.model_dump(mode="json")}
        )
        uid, created = await self.create(
            "live-observation", requester, key, budget, request_hash, "live_question"
        )
        if created:
            self.sources[uid] = "UNKNOWN"
            self.plans[uid] = {
                "start_index": 0,
                "triggered": True,
                "version": "manual-first-response-v1",
            }
            self.tasks[uid] = asyncio.create_task(self.run_live(uid, body, budget))
        return uid

    async def start_call(self, call_id, requester, key, *, reanalyse=False):
        budget = Budgets(decisions=1, tool_calls=0, deadline_seconds=30)
        request_hash = hash_payload(
            {"kind": "call_analysis", "call_id": str(call_id), "reanalyse": reanalyse}
        )
        async with self.call_admission:
            # Short DB transactions never span telemetry network calls.
            async with self.store.pool.acquire(timeout=3) as c:
                previous = await c.fetchrow(
                    "SELECT id,request_hash FROM decision_intel.investigation_sessions WHERE requester=$1 AND idempotency_key=$2",
                    requester,
                    key,
                )
                if previous:
                    if previous["request_hash"] != request_hash:
                        raise ValueError("IDEMPOTENCY_CONFLICT")
                    return previous["id"], True
            saved = await self.store.call_analysis(call_id)
            if saved and (not reanalyse or saved["ended_at"] is None):
                return saved["id"], True
            if await self.store.analysis_busy():
                raise RuntimeError("ANALYSIS_BUSY")
            model = await self.provider.health()
            if model.get("busy"):
                raise RuntimeError("ANALYSIS_BUSY")
            # A missing/unavailable call cannot start model work.
            await self.call_collector.detail(call_id)
            uid, created = await self.create(
                "call-observation",
                requester,
                key,
                budget,
                request_hash,
                "live_question",
                call_id=call_id,
                reanalyse=reanalyse,
            )
            if created:
                self.sources[uid] = "UNKNOWN"
                self.plans[uid] = {
                    "start_index": 0,
                    "triggered": True,
                    "version": "operator-call-analysis-v1",
                }
                self.tasks[uid] = asyncio.create_task(self.run_call(uid, call_id, budget))
            return uid, not created

    async def create(
        self, dataset, requester, key, budget, request_hash, mode, *, call_id=None, reanalyse=False
    ):
        async with self.store.pool.acquire(timeout=3) as c, c.transaction():
            # Cross-process creation cap/dedup serialized in PostgreSQL, not check-then-insert.
            await c.execute("SELECT pg_advisory_xact_lock(948402)")
            row = await c.fetchrow(
                "SELECT id,request_hash FROM decision_intel.investigation_sessions WHERE requester=$1 AND idempotency_key=$2",
                requester,
                key,
            )
            if row:
                if row["request_hash"] != request_hash:
                    raise ValueError("IDEMPOTENCY_CONFLICT")
                return row["id"], False
            if call_id is not None:
                saved = await c.fetchrow(
                    "SELECT s.id,s.ended_at FROM decision_intel.call_analyses a JOIN decision_intel.investigation_sessions s ON s.id=a.session_id WHERE a.call_id=$1 ORDER BY a.created_at DESC,a.session_id DESC LIMIT 1",
                    call_id,
                )
                if saved and (not reanalyse or saved["ended_at"] is None):
                    return saved["id"], False
            active = await c.fetchval(
                "SELECT count(*) FROM decision_intel.investigation_sessions WHERE ended_at IS NULL"
            )
            active_call = await c.fetchval(
                "SELECT EXISTS(SELECT 1 FROM decision_intel.call_analyses a JOIN decision_intel.investigation_sessions s ON s.id=a.session_id WHERE s.ended_at IS NULL)"
            )
            if active >= (1 if call_id is not None else 2) or active_call:
                raise RuntimeError("INVESTIGATION_CAPACITY")
            uid = uuid4()
            await c.execute(
                "INSERT INTO decision_intel.investigation_sessions(id,incident_key,mode,state,requester,idempotency_key,request_hash,policy_version,model_version,budget,dataset_ref) VALUES($1,$2,$9,'NEW',$3,$4,$5,$6,'laya-0.4.3',$7,$8)",
                uid,
                str(uid),
                requester,
                key,
                request_hash,
                VERSION,
                budget.model_dump(),
                dataset,
                mode,
            )
            if call_id is not None:
                await c.execute(
                    "INSERT INTO decision_intel.call_analyses(session_id,call_id) VALUES($1,$2)",
                    uid,
                    call_id,
                )
        return uid, True

    async def run_call(self, uid, call_id, budget):
        started = time.monotonic()
        try:
            await self.store.transition(uid, "COLLECTING", "OPERATOR_REQUESTED_CALL_ANALYSIS")
            async with asyncio.timeout(10):
                state = await self.call_collector.state(call_id)
            age = (datetime.now(timezone.utc) - state.observed_at).total_seconds()
            if not 0 <= age <= 86400:
                raise ValueError("CALL_WINDOW_UNAVAILABLE")
            payload = state.model_dump(mode="json")
            source_hash = hash_payload(payload)
            self.sources[uid] = source_hash
            await self.run(uid, [payload], source_hash, budget, live=True, started_at=started)
            return
        except asyncio.CancelledError:
            await self.store.transition(uid, "CANCELLED", "OPERATOR_CANCEL")
        except Exception:
            await self.store.transition(uid, "ESCALATED", "CALL_EVIDENCE_UNAVAILABLE")
        await self.finalize(
            uid,
            "UNKNOWN",
            {
                "suspected_components": [],
                "conclusion_type": "ESCALATED",
                "reason": "Call evidence unavailable; no diagnosis or actions",
            },
        )

    async def run_live(self, uid, body, budget):
        started = time.monotonic()
        try:
            await self.store.transition(uid, "COLLECTING", "OPERATOR_REQUESTED_LIVE_OBSERVATIONS")
            async with asyncio.timeout(10):
                state = await self.live_collector.collect(
                    Lookup(**body.model_dump(exclude={"error_excerpt"}))
                )
            # Collection does not depend on a running experiment or a recorded file.
            if (
                not self.allow_fixture
                and not 0 <= (datetime.now(timezone.utc) - state.observed_at).total_seconds() <= 15
            ):
                raise ValueError("STALE_LIVE_OBSERVATION")
            if body.error_excerpt:
                state.request_evidence.append(user_evidence(body))
            payload = state.model_dump(mode="json")
            source_hash = hash_payload(payload)
            self.sources[uid] = source_hash
            await self.run(uid, [payload], source_hash, budget, live=True, started_at=started)
            return
        except asyncio.CancelledError:
            await self.store.transition(uid, "CANCELLED", "OPERATOR_CANCEL")
        except Exception:
            await self.store.transition(uid, "ESCALATED", "LIVE_EVIDENCE_UNAVAILABLE")
        await self.finalize(
            uid,
            "UNKNOWN",
            {
                "suspected_components": [],
                "conclusion_type": "ESCALATED",
                "reason": "Live observations unavailable; no diagnosis or actions",
            },
        )

    async def run(self, uid, states, source_hash, budget, *, live=False, started_at=None):
        last_tool = last_signal_hash = None
        conclusion = {
            "suspected_components": [],
            "conclusion_type": "INCONCLUSIVE",
            "reason": "Live first-response suggestion; cause unconfirmed; no model-selected diagnostic execution"
            if live
            else "Recorded evidence supports hypotheses only; no diagnostic execution",
        }
        started = time.monotonic() if started_at is None else started_at
        plan = self.plans.get(uid) or replay_start(states)
        try:
            await self.store.transition(uid, "COLLECTING")
            for step, state in enumerate(
                states[plan["start_index"] : plan["start_index"] + budget.decisions]
            ):
                if time.monotonic() - started >= budget.deadline_seconds:
                    await self.store.transition(uid, "TIMED_OUT", "SESSION_DEADLINE")
                    break
                await self.store.transition(uid, "DECIDING")
                q, request = live_questions() if live else questions(), uuid4()
                question_version = LIVE_QUESTION_VERSION if live else QUESTION_VERSION
                async with self.store.pool.acquire(timeout=3) as c, c.transaction():
                    oid = uuid4()
                    await c.execute(
                        "INSERT INTO decision_intel.observation_snapshots VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
                        oid,
                        uid,
                        step,
                        datetime.fromisoformat(state["observed_at"]),
                        state["window_seconds"],
                        state,
                        state["source_quality"],
                        hash_payload(state),
                    )
                    await c.execute(
                        "INSERT INTO decision_intel.evidence_items VALUES($1,$2,NULL,$3,$4,$5,$6,$7)",
                        oid,
                        uid,
                        "manual_live_observations" if live else "recorded_public_observations",
                        datetime.fromisoformat(state["observed_at"]),
                        state["source_quality"],
                        f"artifact://investigations/{uid}/observations.jsonl#step={step}",
                        hash_payload(state),
                    )
                    await c.execute(
                        "INSERT INTO decision_intel.decision_requests(id,session_id,step,question_set_version,state_hash,available_actions) VALUES($1,$2,$3,$4,$5,$6)",
                        request,
                        uid,
                        step,
                        question_version,
                        hash_payload(state),
                        list(TOOLS),
                    )
                try:
                    async with asyncio.timeout(
                        min(
                            budget.inference_seconds,
                            budget.deadline_seconds - (time.monotonic() - started),
                        )
                    ):
                        response = await self.provider.decide(state, q)
                    validate_provider_result(
                        response,
                        allow_fixture=self.allow_fixture,
                        question_version=question_version,
                    )
                    if live and response["provider_version"] == "laya-0.4.3":
                        from decision_engine.inference_input import validate_quality

                        validate_quality(response["input_quality"], state)
                    answers = normalize_answers({"answers": response["raw_answers"]}, q)
                except Exception as exc:
                    async with self.store.pool.acquire(timeout=3) as c:
                        await c.execute(
                            "INSERT INTO decision_intel.decision_answers VALUES($1,$2,$3,$4,'INVALID',$5,NULL,$6,$7,$8)",
                            request,
                            {"rejected": True},
                            {},
                            {},
                            "unavailable-or-invalid",
                            {
                                "verdict": "ABSTAIN",
                                "execute": False,
                                "override_reason": type(exc).__name__,
                            },
                            baseline(state),
                            [],
                        )
                    await self.store.transition(uid, "ESCALATED", type(exc).__name__)
                    break
                proposal = answers["next_diagnostic_tool"]["choice"]
                # Timestamps do not count as new evidence for repeated tool eligibility.
                signal_hash = hash_payload(
                    {
                        k: state[k]
                        for k in (
                            "api",
                            "database",
                            "redis",
                            "worker",
                            "integrity",
                            "source_quality",
                        )
                    }
                )
                policy = authorize(
                    proposal,
                    state,
                    step=step,
                    mode="shadow",
                    previous=last_tool,
                    changed=signal_hash != last_signal_hash,
                )
                if live:
                    policy["input_quality"] = response.get("input_quality")
                ranking = [
                    {
                        "candidate_action": action,
                        "rank": rank + 1,
                        "model_suitability_probability": value,
                        "policy_eligible": authorize(
                            action,
                            state,
                            step=step,
                            mode="shadow",
                            previous=last_tool,
                            changed=signal_hash != last_signal_hash,
                        )["verdict"]
                        == "ALLOW_READ_ONLY",
                        "empirical_evidence_yield": None,
                        "outcome_verified": False,
                        "score_source": "laya_choice_distribution",
                        "question_version": question_version,
                    }
                    for rank, (action, value) in enumerate(
                        sorted(
                            answers["next_diagnostic_tool"]["probabilities"].items(),
                            key=lambda item: (-item[1], item[0]),
                        )
                    )
                ]
                async with self.store.pool.acquire(timeout=3) as c:
                    await c.execute(
                        "INSERT INTO decision_intel.decision_answers VALUES($1,$2,$3,$4,'VALID',$5,$6,$7,$8,$9)",
                        request,
                        response["raw_answers"],
                        answers,
                        {k: v.get("probabilities") for k, v in answers.items()},
                        response["provider_version"],
                        response["inference_ms"],
                        policy,
                        baseline(state),
                        ranking,
                    )
                last_tool, last_signal_hash = proposal, signal_hash
                await self.store.transition(uid, "EVALUATING")
                if live or detected(states[: plan["start_index"] + step + 1]):
                    conclusion["suspected_components"] = [answers["suspected_subsystem"]["choice"]]
                if policy["verdict"] == "ESCALATE":
                    await self.store.transition(uid, "ESCALATED", "POLICY_ESCALATION")
                    break
            else:
                await self.store.transition(
                    uid,
                    "INCONCLUSIVE",
                    "FIRST_RESPONSE_COMPLETE" if live else "SHADOW_REPLAY_COMPLETE",
                )
        except asyncio.CancelledError:
            await self.store.transition(uid, "CANCELLED", "OPERATOR_CANCEL")
        except Exception as exc:
            await self.store.transition(uid, "ERROR", type(exc).__name__)
        finally:
            await self.finalize(uid, source_hash, conclusion)

    async def finalize(self, uid, source_hash, conclusion):
        try:
            session = await self.store.get(uid)
            if session["state"] != "INCONCLUSIVE":
                conclusion = {
                    **conclusion,
                    "conclusion_type": session["state"],
                    "reason": session["last_error"] or session["state"],
                }
            async with self.store.pool.acquire(timeout=3) as c:
                await c.execute(
                    "INSERT INTO decision_intel.session_conclusions VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING",
                    uid,
                    conclusion["suspected_components"],
                    [],
                    conclusion["conclusion_type"],
                    VERSION,
                    conclusion["reason"],
                )
            from decision_engine.evaluation.export import export_session

            await export_session(self.store, uid, self.reports, source_hash, self.plans.get(uid))
        except Exception:
            await self.store.transition(uid, "ERROR", "ARTIFACT_EXPORT_FAILED", force=True)
        finally:
            self.tasks.pop(uid, None)
            self.sources.pop(uid, None)
            self.plans.pop(uid, None)

    async def _cancel(self, uid):
        task = self.tasks.get(uid)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            row = await self.store.get(uid)
            if row["ended_at"] is None:
                await self.store.transition(uid, "CANCELLED", "OPERATOR_CANCEL")
                await self.finalize(
                    uid,
                    self.sources.get(uid, "UNKNOWN"),
                    {
                        "suspected_components": [],
                        "conclusion_type": "CANCELLED",
                        "reason": "Cancelled before inference; no diagnostics executed",
                    },
                )
        return await self.store.get(uid)

    async def cancel(self, uid):
        # Every caller shares one cancellation/finalization operation. A second
        # request, or its HTTP timeout, must not cancel the evidence writer.
        if uid not in self.cancellations:
            self.cancellations[uid] = asyncio.create_task(self._cancel(uid))
        try:
            return await asyncio.shield(self.cancellations[uid])
        finally:
            if self.cancellations.get(uid) and self.cancellations[uid].done():
                self.cancellations.pop(uid, None)
