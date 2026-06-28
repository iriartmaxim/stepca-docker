#!/usr/bin/env bash
# Demo end-to-end del challenge ACME tls-alpn-01 contra la RA.
# Usa lego (que implementa el servidor TLS-ALPN en :443) en la red de Docker,
# aliased al dominio pedido. El CLI `step` NO hace tls-alpn standalone.
#
# Uso:  examples/acme/demo-tlsalpn01.sh [dominio.local]
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

DOMAIN="${1:-tlsdemo.local}"
LEGO_IMG="goacme/lego:latest"
NAME="acme-tlsalpn-demo"
ROOT_CRT="persistent/ra/ra-one/certs/root_ca.crt"
NET="$(docker inspect stepca-haproxy -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null | head -1)"

[[ -f "${ROOT_CRT}" ]] || { echo "❌ Falta ${ROOT_CRT}. Corré 'make up' primero."; exit 1; }

cleanup() { docker rm -f "${NAME}" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

echo "🌐 Red: ${NET}  |  Dominio: ${DOMAIN}  |  Provisioner: acme-tls (tls-alpn-01)"
docker run -d --name "${NAME}" --user 0 \
  --network "${NET}" --network-alias "${DOMAIN}" \
  --entrypoint sh "${LEGO_IMG}" -c 'sleep 120' >/dev/null
docker cp "${ROOT_CRT}" "${NAME}:/root_ca.crt"

docker exec -e LEGO_CA_CERTIFICATES=/root_ca.crt "${NAME}" sh -c "
  /lego run -s https://stepca-ra-one.local:9100/acme/acme-tls/directory \
    -m demo@${DOMAIN} -a -d ${DOMAIN} --tls &&
  echo '--- certificado emitido ---' &&
  ls -1 /.lego/certificates/
"
echo "✅ Demo tls-alpn-01 OK"
