#!/usr/bin/env bash
set -euo pipefail
shopt -s inherit_errexit


# ── Guard: si ya existe el intermedio, salimos ────────────────────────────
if [ -f "${INTERMEDIATE_TMP_DIR:-/home/step/intermediate_tmp}/certs/intermediate.crt" ]; then
  echo "[root-init] Certificado intermedio ya existe, saltando init."
  exit 0
fi


# ── Validar que existan las vars de entorno ────────────────────────────────
: "${ROOT_PASS_FILE:?Falta definir ROOT_PASS_FILE}"
: "${SUB_PASS_FILE:?Falta definir SUB_PASS_FILE}"
: "${INTERMEDIATE_TMP_DIR:?Falta definir INTERMEDIATE_TMP_DIR}"
: "${CA_URL:?Falta definir CA_URL}"
: "${INTERMEDIATE_DNS:?Falta definir INTERMEDIATE_DNS}"
: "${INTERMEDIATE_KEY_SIZE:?Falta definir INTERMEDIATE_KEY_SIZE}"
: "${INTERMEDIATE_PROFILE:?Falta definir INTERMEDIATE_PROFILE}"

# ── Rutas internas basadas en env ─────────────────────────────────────────
CSR_FILE="${INTERMEDIATE_TMP_DIR}/intermediate.csr"
KEY_FILE="${INTERMEDIATE_TMP_DIR}/secrets/intermediate_ca_key"
CRT_FILE="${INTERMEDIATE_TMP_DIR}/certs/intermediate.crt"

# ── Helper retry ──────────────────────────────────────────────────────────
retry() { local max=$1 delay=$2; shift 2
  for ((i=1;i<=max;i++)); do "$@" && return 0 || sleep "$delay"; done
  echo "ERROR: '$*' fallo tras ${max} intentos" >&2; return 1
}

echo "[root-init] Esperando Root CA en ${CA_URL}…"
retry 20 2 curl -sfk "${CA_URL}"

echo "[root-init] Creando dirs en ${INTERMEDIATE_TMP_DIR}…"
mkdir -p "${INTERMEDIATE_TMP_DIR}/certs" "${INTERMEDIATE_TMP_DIR}/secrets"

echo "[root-init] Generando CSR para ${INTERMEDIATE_DNS}…"
step certificate create "${INTERMEDIATE_DNS}" \
  "${CSR_FILE}" "${KEY_FILE}" \
  --csr \
  --san "${INTERMEDIATE_DNS}" \
  --kty RSA --size "${INTERMEDIATE_KEY_SIZE}" \
  --password-file "${SUB_PASS_FILE}"

echo "[root-init] Firmando CSR con perfil ${INTERMEDIATE_PROFILE}…"
step certificate sign \
  "${CSR_FILE}" \
  "$(step path)/certs/root_ca.crt" \
  "$(step path)/secrets/root_ca_key" \
  --profile "${INTERMEDIATE_PROFILE}" \
  --password-file "${ROOT_PASS_FILE}" \
  > "${CRT_FILE}"

echo "[root-init] Certificado intermedio en ${CRT_FILE}"

