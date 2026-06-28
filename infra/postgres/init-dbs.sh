#!/bin/sh
# Crea las bases de datos separadas para la Intermediate CA y la RA.
# (Cada autoridad usa su propia DB; las réplicas comparten la suya.)
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
  SELECT 'CREATE DATABASE stepca_int' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='stepca_int')\gexec
  SELECT 'CREATE DATABASE stepca_ra'  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='stepca_ra')\gexec
EOSQL
echo "[postgres-init] bases stepca_int y stepca_ra listas"
