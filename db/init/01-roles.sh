#!/bin/sh
# Runs once, on first start of an empty data volume.
# techforce_app is what the API connects as: not a superuser and no BYPASSRLS,
# so row-level security policies always apply to it.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE techforce_app LOGIN PASSWORD '${APP_DB_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE DATABASE techforce_test OWNER ${POSTGRES_USER};
SQL
