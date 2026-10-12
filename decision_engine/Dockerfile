FROM pulsepay-api:v1 AS dependencies
FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS runtime
COPY --from=dependencies /usr/local /usr/local
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
RUN groupadd -g 10001 decision && useradd -u 10001 -g decision -m decision && mkdir /reports && chown decision:decision /reports
WORKDIR /app
COPY decision_engine/__init__.py decision_engine/cli.py decision_engine/http_limits.py decision_engine/inference_input.py /app/decision_engine/
COPY decision_engine/models /app/decision_engine/models
COPY decision_engine/questions /app/decision_engine/questions
COPY decision_engine/providers/base.py decision_engine/providers/laya_provider.py /app/decision_engine/providers/
COPY decision_engine/controller /app/decision_engine/controller
COPY decision_engine/adapters /app/decision_engine/adapters
COPY decision_engine/tools /app/decision_engine/tools
COPY decision_engine/api /app/decision_engine/api
COPY decision_engine/evaluation/export.py /app/decision_engine/evaluation/export.py
COPY chaos/observation_contract.py /app/chaos/observation_contract.py
COPY apps/pulsepay/ui/styles.css /app/decision_engine/api/ui/shared.css
USER decision
CMD ["uvicorn", "decision_engine.api.main:app", "--host", "0.0.0.0", "--port", "8092", "--no-access-log", "--limit-concurrency", "32"]

# Trusted one-shot tooling has evaluator/migration code; investigators do not.
FROM runtime AS tools
COPY decision_engine/evaluation/scorer.py decision_engine/evaluation/design-v1.json /app/decision_engine/evaluation/
COPY decision_engine/setup_roles.py decision_engine/setup_test_db.py decision_engine/migrate_test.py /app/decision_engine/
COPY decision_engine/export_bundles.py /app/decision_engine/export_bundles.py
COPY decision_engine/providers/mock_provider.py /app/decision_engine/providers/mock_provider.py
COPY decision_engine/model_service.py /app/decision_engine/model_service.py
COPY decision_engine/checkpoint.py /app/decision_engine/checkpoint.py
COPY decision_engine/tests /app/decision_engine/tests
COPY decision_engine/pytest.ini /app/decision_engine/pytest.ini
COPY migrations/decision /app/migrations/decision
COPY alembic.decision.ini /app/alembic.decision.ini
