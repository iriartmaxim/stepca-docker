#!/bin/bash
# Entrypoint del STANDBY (corre como root, baja a postgres con gosu):
# si no está inicializado, clona el primario con pg_basebackup (streaming) y
# arranca como hot standby.
set -e
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

mkdir -p "$PGDATA"
chown -R postgres:postgres "$PGDATA"
chmod 0700 "$PGDATA"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "[pg-standby] esperando al primario (pg-primary)…"
  until gosu postgres pg_isready -h pg-primary -p 5432 -U "$POSTGRES_USER" >/dev/null 2>&1; do sleep 2; done
  echo "[pg-standby] clonando con pg_basebackup…"
  rm -rf "${PGDATA:?}"/*
  PGPASSWORD="$REPLICATION_PASSWORD" gosu postgres pg_basebackup \
    -h pg-primary -p 5432 -U replicator \
    -D "$PGDATA" -Fp -Xs -P -R -C -S standby1
  chown -R postgres:postgres "$PGDATA"
  chmod 0700 "$PGDATA"
  echo "[pg-standby] base clonada; arrancando en modo hot standby"
fi

# Debe igualar (o superar) los parámetros del primario, si no Postgres aborta el recovery.
exec docker-entrypoint.sh postgres \
  -c max_connections=200 \
  -c max_wal_senders=10 \
  -c max_replication_slots=10 \
  -c hot_standby=on
