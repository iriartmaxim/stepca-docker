#!/usr/bin/env bash
<<<<<<< HEAD
set -euo pipefail
shopt -s inherit_errexit


=======
# Aprovisiona la CA intermedia de forma idempotente:
#   - copia root_ca.crt, intermediate_ca.crt y la clave intermedia a su lugar
#   - espera a que la Root CA esté disponible
# Diseñado para correr ANTES de `step-ca` (el comando los encadena con &&).
set -euo pipefail
shopt -s inherit_errexit

>>>>>>> main-clean
: "${ROOT_CA_URL:?Falta definir ROOT_CA_URL}"
: "${INTERMEDIATE_TMP_DIR:?Falta definir INTERMEDIATE_TMP_DIR}"
: "${SUB_PASS_FILE:?Falta definir SUB_PASS_FILE}"
: "${ROOT_CRT_SRC:?Falta definir ROOT_CRT_SRC}"

STEP_PATH="$(step path)"

<<<<<<< HEAD
# Fuentes/destinos
INT_CRT_SRC="${INTERMEDIATE_TMP_DIR}/certs/intermediate.crt"
INT_KEY_SRC="${INTERMEDIATE_TMP_DIR}/secrets/intermediate_ca_key"
=======
# Fuentes (generadas por la Root CA en el volumen temporal compartido)
INT_CRT_SRC="${INTERMEDIATE_TMP_DIR}/certs/intermediate.crt"
INT_KEY_SRC="${INTERMEDIATE_TMP_DIR}/secrets/intermediate_ca_key"

# Destinos en el step-path de la intermedia
>>>>>>> main-clean
ROOT_CRT_DST="${STEP_PATH}/certs/root_ca.crt"
INT_CRT_DST="${STEP_PATH}/certs/intermediate_ca.crt"
INT_KEY_DST="${STEP_PATH}/secrets/intermediate_ca_key"

retry() { local max=$1 delay=$2; shift 2
  for ((i=1;i<=max;i++)); do "$@" && return 0 || sleep "$delay"; done
<<<<<<< HEAD
  echo "ERROR: '$*' fallo tras ${max} intentos" >&2; return 1
}

echo "[int-init] Esperando Root CA en ${ROOT_CA_URL}…"
retry 20 2 curl -sfk "${ROOT_CA_URL}"

echo "[int-init] Intermediate lista correctamente"

=======
  echo "ERROR: '$*' falló tras ${max} intentos" >&2; return 1
}

mkdir -p "${STEP_PATH}/certs" "${STEP_PATH}/secrets"

# ── Copia idempotente del material (no pisa si ya existe) ──────────────────
if [ ! -f "${ROOT_CRT_DST}" ] && [ -f "${ROOT_CRT_SRC}" ]; then
  echo "[int-init] Copiando root_ca.crt"
  cp "${ROOT_CRT_SRC}" "${ROOT_CRT_DST}"
fi

if [ ! -f "${INT_CRT_DST}" ]; then
  echo "[int-init] Esperando intermediate.crt de la Root CA…"
  retry 30 2 test -f "${INT_CRT_SRC}"
  cp "${INT_CRT_SRC}" "${INT_CRT_DST}"
fi

if [ ! -f "${INT_KEY_DST}" ]; then
  echo "[int-init] Esperando clave intermedia de la Root CA…"
  retry 30 2 test -f "${INT_KEY_SRC}"
  cp "${INT_KEY_SRC}" "${INT_KEY_DST}"
  chmod 600 "${INT_KEY_DST}" || true
fi

echo "[int-init] Esperando Root CA en ${ROOT_CA_URL}…"
retry 20 2 curl -sfk "${ROOT_CA_URL}"

echo "[int-init] Intermediate aprovisionada correctamente"
>>>>>>> main-clean
