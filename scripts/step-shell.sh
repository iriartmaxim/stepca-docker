#!/usr/bin/env bash
# Cliente operador SEGURO para interactuar con la PKI.
#
# En vez de montar el socket de Docker (root sobre el host), usa la API
# autenticada de step-ca: arranca un contenedor `step` efímero, establece
# confianza con `step ca bootstrap` PINNEANDO la root por fingerprint, y desde
# ahí ejecuta comandos `step ca …` autenticados por provisioner/ACME/admin.
#
# - Sin socket de Docker. Sin claves de CA embebidas.
# - Confianza anclada al fingerprint de la Root (no "confiar a ciegas").
# - Efímero: el contenedor se borra al salir; no deja credenciales en disco.
#
# Uso:
#   scripts/step-shell.sh                      # shell interactivo ya bootstrapeado
#   scripts/step-shell.sh ca health            # ejecuta un comando puntual
#   CA_URL=https://localhost:9001 scripts/step-shell.sh ca provisioner list
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"
envval() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//'; }
IMAGE="$(envval STEPCA_IMAGE)"; IMAGE="${IMAGE:-smallstep/step-ca:0.28.3}"
CA_URL="${CA_URL:-https://stepca-intermediate:9000}"
NET="$(docker inspect stepca-haproxy -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null | head -1)"
ROOT_CRT="persistent/root/certs/root_ca.crt"

[[ -f "${ROOT_CRT}" ]] || { echo "❌ Falta ${ROOT_CRT}. Levantá el stack con 'make up'."; exit 1; }

# Fingerprint de la Root (anclaje de confianza)
FP="$(docker run --rm -v "${ROOT_DIR}/${ROOT_CRT}:/root_ca.crt:ro" --entrypoint step "${IMAGE}" \
        certificate fingerprint /root_ca.crt | tr -d '\r\n')"

BOOT="step ca bootstrap --ca-url ${CA_URL} --fingerprint ${FP} --force >/dev/null 2>&1"

if [[ $# -gt 0 ]]; then
  # Comando puntual (no interactivo)
  docker run --rm --network "${NET}" --entrypoint sh "${IMAGE}" \
    -c "${BOOT}; step $*"
else
  # Shell interactivo endurecido
  echo "🔐 Cliente step efímero · CA ${CA_URL} · root pinneada (${FP:0:16}…)"
  docker run --rm -it --network "${NET}" --entrypoint sh "${IMAGE}" \
    -c "${BOOT}; echo 'Confianza establecida (root pinneada). Ejecutá: step ca …'; exec sh"
fi
