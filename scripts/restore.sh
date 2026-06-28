#!/usr/bin/env bash
# Restaura un backup creado por backup.sh.
# Uso: scripts/restore.sh backups/stepca-YYYYmmdd-HHMMSS.tar.gz
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ARCHIVE="${1:?Uso: restore.sh <archivo.tar.gz>}"

[[ -f "${ARCHIVE}" ]] || { echo "❌ No existe: ${ARCHIVE}" >&2; exit 1; }

cd "${ROOT_DIR}"
echo "⚠️  Esto sobrescribe persistent/ y secrets/ con el backup."
echo "    Archivo: ${ARCHIVE}"
echo "    Ctrl-C para abortar…"; sleep 4

docker compose down || true
echo "♻️  Restaurando…"
tar -xzf "${ARCHIVE}" -C "${ROOT_DIR}"
echo "🚀 Levantando stack…"
docker compose up -d
echo "✅ Restore completo. Verificá con: make test"
