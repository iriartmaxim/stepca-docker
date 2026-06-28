#!/usr/bin/env bash
# Failover de PostgreSQL: promueve el standby a primario.
# Las CAs usan un DSN multi-host con target_session_attrs=read-write, así que
# reconectan solas al nuevo primario una vez promovido.
#
# Uso:  scripts/pg-failover.sh            # promueve pg-standby
#       PROMOTE=pg-standby scripts/pg-failover.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

NODE="${PROMOTE:-pg-standby}"
echo "⚠️  Promoviendo ${NODE} a primario…"
docker exec "${NODE}" gosu postgres pg_ctl promote -D /var/lib/postgresql/data
sleep 3
echo "=== estado de recovery (f = ya es primario) ==="
docker exec "${NODE}" psql -U "${PG_USER:-stepca}" -tAc "SELECT pg_is_in_recovery();"
echo "✅ ${NODE} promovido. Las CAs reconectarán al nuevo primario (multi-host DSN)."
echo "ℹ️  Para reconstruir el ex-primario como standby: borralo y recreá su volumen,"
echo "    o re-clonalo con pg_basebackup contra el nuevo primario."
