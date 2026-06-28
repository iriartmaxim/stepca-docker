#!/usr/bin/env bash
# Backup consistente del estado de las CAs (DB badger + config + certs).
# Detiene brevemente los servicios para garantizar consistencia de badger.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_DIR}/stepca-${STAMP}.tar.gz"
NO_STOP="${NO_STOP:-}"

cd "${ROOT_DIR}"
mkdir -p "${BACKUP_DIR}"

if [[ "${NO_STOP}" != "1" ]]; then
  echo "⏸  Deteniendo servicios para snapshot consistente…"
  docker compose stop
  trap 'echo "▶  Reiniciando servicios…"; docker compose start' EXIT
fi

echo "📦 Creando backup en ${DEST}…"
tar -czf "${DEST}" persistent secrets 2>/dev/null
echo "✅ Backup creado: ${DEST}"
echo "   $(du -h "${DEST}" | cut -f1)  |  retené esto en lugar seguro (contiene claves)."

# Rotación: conserva los últimos N (default 7)
KEEP="${KEEP:-7}"
ls -1t "${BACKUP_DIR}"/stepca-*.tar.gz 2>/dev/null | tail -n +"$((KEEP+1))" | xargs -r rm -f
echo "🧹 Backups conservados: hasta ${KEEP} más recientes."
