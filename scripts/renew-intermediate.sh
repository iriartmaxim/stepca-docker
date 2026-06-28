#!/usr/bin/env bash
# Renueva el certificado de la CA intermedia antes de su expiración.
# Pensado para correr periódicamente (cron/systemd timer). Idempotente:
# solo renueva si quedan menos de RENEW_THRESHOLD_DAYS para vencer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RENEW_THRESHOLD_DAYS="${RENEW_THRESHOLD_DAYS:-30}"
INT_CRT="${ROOT_DIR}/persistent/intermediate/certs/intermediate_ca.crt"
ROOT_PASS="${ROOT_DIR}/secrets/root_ca_password.txt"

[[ -f "${INT_CRT}" ]] || { echo "❌ No se encuentra ${INT_CRT}" >&2; exit 1; }

# Días hasta expiración
not_after="$(openssl x509 -in "${INT_CRT}" -noout -enddate | cut -d= -f2)"
exp_epoch="$(date -d "${not_after}" +%s 2>/dev/null || date -j -f "%b %d %T %Y %Z" "${not_after}" +%s)"
now_epoch="$(date +%s)"
days_left=$(( (exp_epoch - now_epoch) / 86400 ))

echo "ℹ️  La intermedia vence en ${days_left} días (umbral: ${RENEW_THRESHOLD_DAYS})."

if (( days_left > RENEW_THRESHOLD_DAYS )); then
  echo "✅ Aún válida, no se renueva."
  exit 0
fi

echo "🔁 Renovando la CA intermedia con la Root CA…"
docker exec stepca-root step certificate sign \
  /home/step/intermediate_tmp/intermediate.csr \
  "$(docker exec stepca-root step path)/certs/root_ca.crt" \
  "$(docker exec stepca-root step path)/secrets/root_ca_key" \
  --profile intermediate-ca \
  --password-file /run/secrets/ca_password \
  > "${INT_CRT}"

echo "♻️  Recargando las réplicas de la intermedia…"
# Post-HA: la intermedia corre como réplicas stepca-int-1 / stepca-int-2 (mismo cert
# por volumen compartido). Se reinician ambas para que tomen el cert renovado.
docker compose restart stepca-int-1 stepca-int-2
echo "✅ Intermedia renovada."
