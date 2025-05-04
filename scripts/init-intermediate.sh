#!/usr/bin/env bash
set -euo pipefail
shopt -s inherit_errexit


: "${ROOT_CA_URL:?Falta definir ROOT_CA_URL}"
: "${INTERMEDIATE_TMP_DIR:?Falta definir INTERMEDIATE_TMP_DIR}"
: "${SUB_PASS_FILE:?Falta definir SUB_PASS_FILE}"
: "${ROOT_CRT_SRC:?Falta definir ROOT_CRT_SRC}"

STEP_PATH="$(step path)"

# Fuentes/destinos
INT_CRT_SRC="${INTERMEDIATE_TMP_DIR}/certs/intermediate.crt"
INT_KEY_SRC="${INTERMEDIATE_TMP_DIR}/secrets/intermediate_ca_key"
ROOT_CRT_DST="${STEP_PATH}/certs/root_ca.crt"
INT_CRT_DST="${STEP_PATH}/certs/intermediate_ca.crt"
INT_KEY_DST="${STEP_PATH}/secrets/intermediate_ca_key"

retry() { local max=$1 delay=$2; shift 2
  for ((i=1;i<=max;i++)); do "$@" && return 0 || sleep "$delay"; done
  echo "ERROR: '$*' fallo tras ${max} intentos" >&2; return 1
}

echo "[int-init] Esperando Root CA en ${ROOT_CA_URL}…"
retry 20 2 curl -sfk "${ROOT_CA_URL}"

echo "[int-init] Intermediate lista correctamente"

