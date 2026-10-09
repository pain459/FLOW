#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$APP_PASSWORD" -v worker_password="$WORKER_PASSWORD" \
  -v verifier_password="$VERIFIER_PASSWORD" -v migrator_password="$MIGRATOR_PASSWORD" <<'SQL'
CREATE ROLE pulsepay_app LOGIN PASSWORD :'app_password';
CREATE ROLE pulsepay_worker LOGIN PASSWORD :'worker_password';
CREATE ROLE pulsepay_verifier LOGIN PASSWORD :'verifier_password';
CREATE ROLE pulsepay_migrator LOGIN PASSWORD :'migrator_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO pulsepay_migrator;
GRANT USAGE ON SCHEMA public TO pulsepay_app, pulsepay_worker, pulsepay_verifier;
SQL
