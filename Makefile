.PHONY: bootstrap up down test smoke verify breathe stop-breathe status logs reset-lab seed lint observe-test baseline recovery-test
recovery-test:
	sh scripts/recovery-test.sh
observe-test:
	docker compose run --rm -e OBSERVABILITY_TEST=true tests pytest -q tests/e2e/test_observability.py
baseline:
	sh scripts/baseline.sh
bootstrap:
	sh scripts/bootstrap.sh
up:
	docker compose up --build -d
down:
	docker compose --profile observability --profile activity --profile verify down
test:
	sh scripts/test.sh
lint:
	docker compose run --rm tests sh -c 'ruff check . && ruff format --check . && mypy apps shared workers verifier activity'
logs:
	docker compose logs -f api outbox-relay event-worker
seed:
	sh scripts/seed.sh
breathe:
	sh scripts/seed.sh
	ACTIVITY_ENABLED=true docker compose --profile observability --profile activity up --build -d
stop-breathe:
	docker compose --profile activity stop activity
verify:
	sh scripts/verify.sh
smoke:
	sh scripts/smoke.sh
status:
	sh scripts/status.sh
reset-lab:
	sh scripts/reset-lab.sh
