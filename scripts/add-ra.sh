#!/usr/bin/env bash
# Despliega una Autoridad de Registro (RA, modo ACME) para una intermedia adicional <id>.
# La RA usa un provisioner JWK 'ra_jwk' en la intermedia para pedirle certificados.
#
# Uso:  scripts/add-ra.sh <int-id> [puerto-host]
#   ej: scripts/add-ra.sh e 9101
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
ID="${1:?Falta <id> de la intermedia}"
PORT="${2:-9101}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"; cd "${ROOT_DIR}"
envval(){ grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//'; }
IMAGE="$(envval STEPCA_IMAGE)"; IMAGE="${IMAGE:-smallstep/step-ca:0.28.3}"
PG_USER="$(envval PG_USER)"; PG_USER="${PG_USER:-stepca}"
PG_PASSWORD="$(envval PG_PASSWORD)"; PG_PASSWORD="${PG_PASSWORD:-stepca-change-me}"
NET="$(basename "${ROOT_DIR}")_default"

INT_DIR="persistent/intermediate-${ID}"
[[ -f "${INT_DIR}/web_provisioner_password" ]] || { echo "❌ No existe la intermedia '${ID}' (${INT_DIR})"; exit 1; }
INT_ALIAS="stepca-intermediate-${ID}"; INT_URL="https://${INT_ALIAS}:9000"
RA_DIR="persistent/ra/ra-${ID}"; RA_DB="stepca_ra_${ID}"
DSN_RA="postgresql://${PG_USER}:${PG_PASSWORD}@pg-primary:5432,pg-standby:5432/${RA_DB}?target_session_attrs=read-write&sslmode=disable"
mkdir -p "${RA_DIR}"/{config,certs,secrets}

echo "▶ [1/5] Par de claves ra_jwk de la RA…"
if [[ ! -f "${RA_DIR}/secrets/ra.key.pem" || ! -f "${RA_DIR}/secrets/ra_jwk.pub.json" ]]; then
  GEN="$(docker run --rm --entrypoint sh "${IMAGE}" -c '
    step crypto jwk create /tmp/pub.json /tmp/priv.json --kty EC --crv P-256 --no-password --insecure >/dev/null 2>&1
    step crypto key format /tmp/priv.json --pem --pkcs8 --no-password --insecure --out /tmp/ra.key.pem </dev/null 2>/dev/null
    echo "===PUBJWK==="; cat /tmp/pub.json; echo; echo "===RAKEY==="; cat /tmp/ra.key.pem; echo')"
  printf '%s\n' "${GEN}" | sed -n '/===PUBJWK===/,/===RAKEY===/p' | sed '1d;$d' > "${RA_DIR}/secrets/ra_jwk.pub.json"
  printf '%s\n' "${GEN}" | sed -n '/===RAKEY===/,$p'            | sed '1d'    > "${RA_DIR}/secrets/ra.key.pem"
fi
cp -f persistent/root/certs/root_ca.crt "${RA_DIR}/certs/" 2>/dev/null || true
cp -f "${INT_DIR}/certs/intermediate_ca.crt" "${RA_DIR}/certs/" 2>/dev/null || true

echo "▶ [2/5] Alta del provisioner ra_jwk en la intermedia '${ID}' (Admin API)…"
docker run --rm --network "${NET}" \
  -v "${ROOT_DIR}/persistent/root/certs/root_ca.crt:/r.crt:ro" \
  -v "${ROOT_DIR}/${RA_DIR}/secrets/ra_jwk.pub.json:/pub.json:ro" \
  -v "${ROOT_DIR}/${INT_DIR}/web_provisioner_password:/wpw:ro" \
  --entrypoint sh "${IMAGE}" -c "
    step ca provisioner add ra_jwk --type JWK --public-key /pub.json \
      --admin-provisioner web --admin-subject step --admin-password-file /wpw \
      --ca-url ${INT_URL} --root /r.crt 2>&1 | tail -2 || true"

echo "▶ [3/5] Fingerprint de la Root y config de la RA…"
FP="$(docker exec stepca-root step certificate fingerprint /home/step/certs/root_ca.crt | tr -d '\r\n')"
cat > "${RA_DIR}/config/ca.json" <<EOF
{
  "address": ":9100",
  "dnsNames": ["stepca-ra-${ID}","localhost"],
  "db": {"type": "postgresql", "dataSource": "${DSN_RA}"},
  "logger": {"format": "text"},
  "authority": {
    "type": "stepcas",
    "certificateAuthority": "${INT_URL}",
    "certificateAuthorityFingerprint": "${FP}",
    "certificateIssuer": { "type": "jwk", "provisioner": "ra_jwk", "key": "/home/step/secrets/ra.key.pem" },
    "provisioners": [
      { "type": "ACME", "name": "acme-http", "challenges": ["http-01"],
        "policy": { "x509": { "allow": { "dns": ["*.local"] }, "allowWildcardNames": false } } },
      { "type": "ACME", "name": "acme-dns", "challenges": ["dns-01"],
        "policy": { "x509": { "allow": { "dns": ["*.local","*.test"] }, "allowWildcardNames": true } } }
    ]
  },
  "tls": { "minVersion": 1.2, "maxVersion": 1.3, "renegotiation": false }
}
EOF

echo "▶ [4/5] Base de datos ${RA_DB}…"
docker exec pg-primary psql -U "${PG_USER}" -tAc "SELECT 1 FROM pg_database WHERE datname='${RA_DB}'" 2>/dev/null | grep -q 1 \
  || docker exec pg-primary createdb -U "${PG_USER}" "${RA_DB}"

echo "▶ [5/5] Servicio compose de la RA…"
cat > "compose.ra-${ID}.yaml" <<EOF
# RA (ACME) para la intermedia '${ID}'. Uso:
#   docker compose -f compose.yaml -f compose.int-${ID}.yaml -f compose.ra-${ID}.yaml up -d stepca-ra-${ID}
services:
  stepca-ra-${ID}:
    image: ${IMAGE}
    container_name: stepca-ra-${ID}
    restart: unless-stopped
    depends_on: { pg-primary: { condition: service_healthy } }
    networks:
      default:
        aliases: [ "stepca-ra-${ID}" ]
    volumes:
      - ./${RA_DIR}/config:/home/step/config
      - ./${RA_DIR}/certs:/home/step/certs
      - ./${RA_DIR}/secrets:/home/step/secrets
    command: sh -c "step-ca /home/step/config/ca.json"
    healthcheck:
      test: ["CMD","step","ca","health","--ca-url","https://localhost:9100"]
      interval: 10s
      timeout: 5s
      retries: 12
    ports: [ "${PORT}:9100" ]

  # Registra esta RA en el tablero Estado de la UI
  stepca-ui:
    environment:
      RA_${ID^^}: "RA ${ID}|https://stepca-ra-${ID}:9100"
EOF

echo "✅ RA de '${ID}' lista: config en ${RA_DIR}, DB ${RA_DB}, compose.ra-${ID}.yaml (puerto ${PORT})."
