#!/usr/bin/env bash
# Demo end-to-end del challenge ACME http-01 contra la RA.
# Levanta un cliente efímero en la red de Docker, aliased al dominio pedido,
# y solicita un certificado usando el provisioner acme-http (modo standalone).
#
# Uso:  examples/acme/demo-http01.sh [dominio.local]
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

DOMAIN="${1:-demo.local}"
IMAGE="$(grep -E '^STEPCA_IMAGE=' .env 2>/dev/null | cut -d= -f2-)"; IMAGE="${IMAGE:-smallstep/step-ca:0.28.3}"
NET="$(docker inspect stepca-haproxy -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null | head -1)"
ROOT_CRT="persistent/ra/ra-one/certs/root_ca.crt"
NAME="acme-http01-demo"

[[ -f "${ROOT_CRT}" ]] || { echo "❌ Falta ${ROOT_CRT}. ¿Levantaste el stack con 'make up'?"; exit 1; }

cleanup() { docker rm -f "${NAME}" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

echo "🌐 Red: ${NET}  |  Dominio: ${DOMAIN}  |  Provisioner: acme-http"
docker run -d --name "${NAME}" --user 0 \
  --network "${NET}" --network-alias "${DOMAIN}" \
  --entrypoint sh "${IMAGE}" -c 'sleep 120' >/dev/null
docker cp "${ROOT_CRT}" "${NAME}:/root_ca.crt"

docker exec "${NAME}" sh -c "
  step ca certificate ${DOMAIN} /tmp/d.crt /tmp/d.key \
    --provisioner acme-http \
    --ca-url https://stepca-ra-one.local:9100 \
    --root /root_ca.crt --standalone &&
  echo '--- certificado emitido ---' &&
  step certificate inspect /tmp/d.crt --short
"
# Depositar el cert en el inventario que visualiza la UI
mkdir -p persistent/issued
docker cp "${NAME}:/tmp/d.crt" "persistent/issued/${DOMAIN}.crt" 2>/dev/null \
  && echo "📥 Cert guardado en persistent/issued/${DOMAIN}.crt"
echo "✅ Demo http-01 OK"
