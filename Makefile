.PHONY: bootstrap up down test smoke verify status logs reset-lab seed lint observe-test baseline recovery-test ui-test
ui-test:
	sh scripts/ui-test.sh
recovery-test:
	sh scripts/recovery-test.sh
observe-test:
	docker compose run --rm -e OBSERVABILITY_TEST=true tests pytest -q tests/e2e/test_observability.py
baseline:
	sh scripts/load-qualify.sh
bootstrap:
	sh scripts/bootstrap.sh
up:
	docker compose --profile observability up --build -d
down:
	docker compose --profile observability --profile verify down
test:
	sh scripts/test.sh
lint:
	docker compose run --rm tests sh -c 'ruff check . && ruff format --check . && mypy apps shared workers verifier'
logs:
	docker compose logs -f api outbox-relay event-worker
seed:
	sh scripts/seed.sh
verify:
	sh scripts/verify.sh
smoke:
	sh scripts/smoke.sh
status:
	sh scripts/status.sh
reset-lab:
	sh scripts/reset-lab.sh

.PHONY: load-smoke load-run load-stop load-report load-preflight load-test
load-smoke:
	sh scripts/load-smoke.sh
load-run:
	sh scripts/load-run.sh
load-stop:
	sh scripts/load-stop.sh
load-report:
	sh scripts/load-report.sh
load-preflight:
	sh scripts/load-preflight.sh
load-test:
	docker compose -f compose.yaml -f compose.load.yaml run --rm --no-deps load-controller pytest -q load_generator/tests

.PHONY: load-qualify load-ui
load-ui:
	docker compose up -d locust
	@echo 'Locust UI: http://127.0.0.1:8089 (idle until Start; duration set by LOCUST_DURATION_SECONDS)'
load-qualify:
	sh scripts/load-qualify.sh
