#!/bin/bash
# Init del PRIMARIO: crea el rol de replicación, las dos bases y habilita
# la replicación en pg_hba. Corre una sola vez (docker-entrypoint-initdb.d).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
  CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '${REPLICATION_PASSWORD}';
  SELECT 'CREATE DATABASE stepca_int' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='stepca_int')\gexec
  SELECT 'CREATE DATABASE stepca_ra'  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='stepca_ra')\gexec
EOSQL

# Permitir conexiones de replicación desde la red interna de Docker
echo "host replication replicator all scram-sha-256" >> "$PGDATA/pg_hba.conf"
echo "[pg-primary] rol replicator, bases stepca_int/stepca_ra y pg_hba listos"
