#!/usr/bin/env bash
# Genera contraseñas fuertes para todos los secretos del stack.
# No sobrescribe archivos existentes salvo que se pase --force.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="${SCRIPT_DIR}/../secrets"
FORCE="${1:-}"

gen() { openssl rand -base64 32 2>/dev/null | tr -d '\n'; }

mkdir -p "${SECRETS_DIR}"

for name in root_ca_password intermediate_ca_password ra_password admin_password; do
  dest="${SECRETS_DIR}/${name}.txt"
  if [[ -f "${dest}" && "${FORCE}" != "--force" ]]; then
    echo "⏭  ${name}.txt ya existe (usa --force para regenerar)"
    continue
  fi
  gen > "${dest}"
  chmod 600 "${dest}" 2>/dev/null || true
  echo "🔐 Generado ${name}.txt"
done

echo "✅ Secretos listos en ${SECRETS_DIR}"
echo "⚠️  Estos archivos están en .gitignore y NO deben versionarse."
