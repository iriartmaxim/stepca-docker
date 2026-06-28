#!/usr/bin/env bash
# Demo end-to-end del challenge ACME dns-01.
# Levanta CoreDNS (zona "local"), hace que la RA lo use como resolver y pide un
# cert con lego usando el hook 'exec' que publica el TXT _acme-challenge.*
#
# Uso:  examples/acme/demo-dns01.sh [dominio.local]
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

# Se usa .test (no .local): .local es mDNS y el resolver de step-ca no lo valida.
DOMAIN="${1:-dnsdemo.test}"
PROJECT="$(basename "${ROOT_DIR}")"
ZVOL="${PROJECT}_acme-zones"
LEGO_IMG="goacme/lego:latest"
NAME="acme-dns01-demo"
ROOT_CRT="persistent/ra/ra-one/certs/root_ca.crt"

[[ -f "${ROOT_CRT}" ]] || { echo "❌ Falta ${ROOT_CRT}. Corré 'make up' primero."; exit 1; }

echo "🌐 [1/4] Levantando CoreDNS y reconfigurando la RA…"
# Sembrar la zona inicial en el volumen ANTES de arrancar CoreDNS
docker volume create "${ZVOL}" >/dev/null
# Sembrar zona limpia y vaciar records previos (TXT duplicados hacen fallar dns-01)
docker run --rm -i -v "${ZVOL}:/zones" --entrypoint sh alpine:3 \
  -c 'cat > /zones/db.test; : > /zones/records' < examples/acme/coredns/db.test
docker compose -f compose.yaml -f compose.acme-demo.yaml up -d --force-recreate challenge-dns
sleep 3
docker compose -f compose.yaml -f compose.acme-demo.yaml up -d --force-recreate stepca-ra-one.local
# esperar RA sana de nuevo
for i in $(seq 1 20); do curl -sfk --max-time 3 https://localhost:9100/health >/dev/null && break; sleep 2; done

echo "🔑 [2/4] Preparando cliente lego (en la red acme-demo, junto a CoreDNS)…"
NET="${PROJECT}_acme-demo"
docker rm -f "${NAME}" >/dev/null 2>&1 || true
docker run -d --name "${NAME}" --user 0 --network "${NET}" \
  -v "${ZVOL}:/zones" --entrypoint sh "${LEGO_IMG}" -c 'sleep 180' >/dev/null
docker cp "${ROOT_CRT}" "${NAME}:/root_ca.crt"
docker cp examples/acme/lego-exec.sh "${NAME}:/exec.sh"
docker exec "${NAME}" chmod +x /exec.sh

echo "📜 [3/4] Solicitando cert para ${DOMAIN} vía dns-01…"
docker exec \
  -e LEGO_CA_CERTIFICATES=/root_ca.crt \
  -e EXEC_PATH=/exec.sh \
  -e DNS_IP=172.31.0.53 \
  "${NAME}" sh -c "/lego run -s https://stepca-ra-one.local:9100/acme/acme-dns/directory \
    -m demo@${DOMAIN} -a -d ${DOMAIN} \
    --dns exec --dns.resolvers 172.31.0.53:53 --dns.propagation.wait 8s 2>&1 | tail -14"

echo "🔍 [4/4] Cert emitido:"
docker exec "${NAME}" sh -c 'ls -1 /.lego/certificates/ 2>/dev/null'
docker rm -f "${NAME}" >/dev/null 2>&1 || true
echo "✅ Demo dns-01 finalizado"
echo "ℹ️  Para revertir la RA a su DNS normal:  docker compose up -d --force-recreate stepca-ra-one.local"
