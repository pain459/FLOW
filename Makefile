.PHONY: bootstrap up down test smoke verify status logs reset-lab seed lint observe-test baseline recovery-test ui-test chaos-list chaos-validate chaos-preflight chaos-run chaos-abort chaos-restore chaos-report chaos-stop chaos-test chaos-recovery-test
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
	docker compose --profile observability --profile chaos up --build -d
down:
	sh scripts/down.sh
test:
	sh scripts/test.sh
lint:
	docker compose run --rm tests sh -c 'ruff check . && ruff format --check . && mypy --explicit-package-bases --exclude "(^|/)tests/" apps shared workers verifier load_generator chaos'
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
chaos-list:
	sh chaos/scripts/experiment.sh list
chaos-validate:
	sh chaos/scripts/experiment.sh validate $(SCENARIO)
chaos-preflight:
	sh chaos/scripts/experiment.sh preflight $(SCENARIO)
chaos-run:
	sh chaos/scripts/experiment.sh run $(SCENARIO)
chaos-abort:
	sh chaos/scripts/abort.sh
chaos-restore:
	sh chaos/scripts/restore.sh verify
chaos-report:
	sh chaos/scripts/report.sh $(RUN_ID)
chaos-test:
	docker compose -f compose.yaml -f compose.chaos.yaml build chaos-runner
	docker compose -f compose.yaml -f compose.chaos.yaml --profile chaos run --rm --no-deps --entrypoint pytest chaos-runner -c /dev/null -p no:cacheprovider -q chaos/tests
chaos-recovery-test:
	sh chaos/scripts/test-recovery.sh
chaos-stop:
	sh chaos/scripts/stop.sh
