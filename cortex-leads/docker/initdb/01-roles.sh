#!/bin/sh
# cl_app: runtime role, not owner, subject to RLS. cl_supervisor: column-granted, no login.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
CREATE ROLE cl_app LOGIN PASSWORD '${CL_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
CREATE ROLE cl_supervisor NOLOGIN NOSUPERUSER NOBYPASSRLS;
SQL
