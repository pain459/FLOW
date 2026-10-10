FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS build
WORKDIR /build
COPY requirements.lock ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.lock

FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
RUN groupadd -g 10001 pulsepay && useradd -u 10001 -g pulsepay -m pulsepay
COPY --from=build /install /usr/local
WORKDIR /app
COPY --chown=pulsepay:pulsepay apps apps
COPY --chown=pulsepay:pulsepay shared shared
COPY --chown=pulsepay:pulsepay workers workers
COPY --chown=pulsepay:pulsepay verifier verifier
COPY --chown=pulsepay:pulsepay migrations migrations
COPY --chown=pulsepay:pulsepay tests tests
COPY --chown=pulsepay:pulsepay scripts scripts
COPY --chown=pulsepay:pulsepay observability observability
COPY --chown=pulsepay:pulsepay pyproject.toml alembic.ini ./
USER pulsepay
CMD ["uvicorn", "apps.pulsepay.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--limit-concurrency", "128", "--backlog", "128", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "15"]
