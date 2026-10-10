FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS build
WORKDIR /build
COPY load_generator/requirements.lock ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.lock

FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
RUN groupadd -g 10001 pulsepay && useradd -u 10001 -g pulsepay -m pulsepay && mkdir /reports && chown pulsepay:pulsepay /reports
COPY --from=build /install /usr/local
WORKDIR /app
COPY --chown=pulsepay:pulsepay load_generator load_generator
COPY --chown=pulsepay:pulsepay shared shared
COPY --chown=pulsepay:pulsepay verifier verifier
COPY --chown=pulsepay:pulsepay apps/pulsepay/schemas apps/pulsepay/schemas
COPY --chown=pulsepay:pulsepay tests tests
USER pulsepay
CMD ["python", "-m", "load_generator.controller.cli", "run", "--profile", "smoke"]
