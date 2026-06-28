#!/usr/bin/env bash
# Orquesta el despliegue HA completo (PostgreSQL + réplicas + HAProxy) sin pasos
# manuales: genera secretos, el par de claves ra_jwk, las configs (PostgreSQL) y
# levanta los servicios en orden.
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# Lee una variable de .env, limpiando comentario inline y espacios (como compose)
envval() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- \
           | sed 's/[[:space:]]*#.*$//' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'; }
IMAGE="$(envval STEPCA_IMAGE)"; IMAGE="${IMAGE:-smallstep/step-ca:0.28.3}"
PG_USER="$(envval PG_USER)";    PG_USER="${PG_USER:-stepca}"
PG_PASSWORD="$(envval PG_PASSWORD)"; PG_PASSWORD="${PG_PASSWORD:-stepca-change-me}"
REPLICATION_PASSWORD="$(envval REPLICATION_PASSWORD)"; REPLICATION_PASSWORD="${REPLICATION_PASSWORD:-repl-change-me}"
INT_PORT="$(envval INTERMEDIATE_PORT)"; INT_PORT="${INT_PORT:-9001}"
RA_PORT="$(envval RA_PORT)"; RA_PORT="${RA_PORT:-9100}"
COMPOSE="docker compose"

INT_CFG="persistent/intermediate/config/ca.json"
RA_DIR="persistent/ra/ra-one"
RA_KEY="${RA_DIR}/secrets/ra.key.pem"
RA_PUB="${RA_DIR}/secrets/ra_jwk.pub.json"
# DSN multi-host: pgx usa el nodo read-write (primario) y reconecta al nuevo
# primario tras un failover (target_session_attrs=read-write).
PG_HOSTS="pg-primary:5432,pg-standby:5432"
DSN_INT="postgresql://${PG_USER}:${PG_PASSWORD}@${PG_HOSTS}/stepca_int?target_session_attrs=read-write&sslmode=disable"
DSN_RA="postgresql://${PG_USER}:${PG_PASSWORD}@${PG_HOSTS}/stepca_ra?target_session_attrs=read-write&sslmode=disable"

wait_health() { # url, intentos
  for i in $(seq 1 "${2:-40}"); do
    curl -sfk --max-time 3 "$1" >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

echo "▶ [1/8] Secretos…"
bash scripts/gen-secrets.sh

echo "▶ [2/8] Estructura de carpetas…"
mkdir -p persistent/root/{config,certs,secrets} \
         persistent/intermediate/{config,certs,secrets} \
         persistent/tmp persistent/issued "${RA_DIR}"/{config,certs,secrets}

echo "▶ [3/8] Par de claves del provisioner ra_jwk…"
if [[ ! -f "${RA_KEY}" || ! -f "${RA_PUB}" ]]; then
  GEN="$(docker run --rm --entrypoint sh "${IMAGE}" -c '
    step crypto jwk create /tmp/pub.json /tmp/priv.json --kty EC --crv P-256 --no-password --insecure >/dev/null 2>&1
    step crypto key format /tmp/priv.json --pem --pkcs8 --no-password --insecure --out /tmp/ra.key.pem </dev/null 2>/dev/null
    echo "===PUBJWK==="; cat /tmp/pub.json; echo
    echo "===RAKEY===";  cat /tmp/ra.key.pem; echo
  ')"
  printf '%s\n' "${GEN}" | sed -n '/===PUBJWK===/,/===RAKEY===/p' | sed '1d;$d' > "${RA_PUB}"
  printf '%s\n' "${GEN}" | sed -n '/===RAKEY===/,$p'            | sed '1d'    > "${RA_KEY}"
  chmod 600 "${RA_KEY}" 2>/dev/null || true
  echo "  ✔ par de claves generado"
else
  echo "  ⏭ ya existe (reutilizando)"
fi
PUBJWK="$(cat "${RA_PUB}")"

echo "▶ [3c] Provisioner 'web' para emisión segura desde la UI…"
WEB_DIR="persistent/ui"; mkdir -p "${WEB_DIR}"
WEB_PW_FILE="${WEB_DIR}/web_provisioner_password"
[[ -f "${WEB_PW_FILE}" ]] || { openssl rand -base64 24 | tr -d '\n' > "${WEB_PW_FILE}"; }
WEB_PW="$(cat "${WEB_PW_FILE}")"
if [[ ! -f "${WEB_DIR}/web.pub.json" || ! -f "${WEB_DIR}/web.ek.txt" ]]; then
  WGEN="$(docker run --rm -e WEBPW="${WEB_PW}" --entrypoint sh "${IMAGE}" -c '
    printf "%s" "$WEBPW" > /tmp/pw
    step crypto jwk create /tmp/pub.json /tmp/key.json --kty EC --crv P-256 --password-file /tmp/pw >/dev/null 2>&1
    P=$(grep "\"protected\""     /tmp/key.json | sed "s/.*: \"\(.*\)\".*/\1/")
    E=$(grep "\"encrypted_key\"" /tmp/key.json | sed "s/.*: \"\(.*\)\".*/\1/")
    IV=$(grep "\"iv\""           /tmp/key.json | sed "s/.*: \"\(.*\)\".*/\1/")
    C=$(grep "\"ciphertext\""    /tmp/key.json | sed "s/.*: \"\(.*\)\".*/\1/")
    T=$(grep "\"tag\""           /tmp/key.json | sed "s/.*: \"\(.*\)\".*/\1/")
    echo "===PUB==="; cat /tmp/pub.json; echo
    echo "===EK==="; echo "$P.$E.$IV.$C.$T"
  ')"
  printf '%s\n' "${WGEN}" | sed -n '/===PUB===/,/===EK===/p' | sed '1d;$d' > "${WEB_DIR}/web.pub.json"
  printf '%s\n' "${WGEN}" | sed -n '/===EK===/,$p' | sed '1d' | tr -d '\n'    > "${WEB_DIR}/web.ek.txt"
  echo "  ✔ provisioner web generado"
else
  echo "  ⏭ ya existe (reutilizando)"
fi
WEB_PUB="$(cat "${WEB_DIR}/web.pub.json")"
WEB_EK="$(cat "${WEB_DIR}/web.ek.txt")"

echo "▶ [3b] Config de la Intermediate CA (PostgreSQL + provisioners ra_jwk/web)…"
cat > "${INT_CFG}" <<EOF
{
  "root": "/home/step/certs/root_ca.crt",
  "crt":  "/home/step/certs/intermediate_ca.crt",
  "key":  "/home/step/secrets/intermediate_ca_key",
  "address": ":9000",
  "dnsNames": ["stepca-intermediate","localhost"],
  "logger": {"format": "text"},
  "db": {"type": "postgresql", "dataSource": "${DSN_INT}"},
  "authority": {
    "enableAdmin": true,
    "claims": { "minTLSCertDuration": "5m", "maxTLSCertDuration": "24h", "defaultTLSCertDuration": "24h" },
    "provisioners": [
      { "type": "JWK", "name": "web", "key": ${WEB_PUB}, "encryptedKey": "${WEB_EK}",
        "policy": { "x509": { "allow": { "dns": ["*.local"] }, "allowWildcardNames": false } },
        "options": { "x509": { "templateFile": "/home/step/templates/web-leaf.tpl" } } },
      { "type": "JWK", "name": "ra_jwk", "key": ${PUBJWK} }
    ]
  }
}
EOF

echo "▶ [4/8] PostgreSQL (primario + standby)…"
${COMPOSE} up -d pg-primary
echo "  ⏳ esperando al primario…"
for i in $(seq 1 40); do
  docker exec pg-primary pg_isready -U "${PG_USER}" -d stepca_int >/dev/null 2>&1 && break
  sleep 2; [[ $i -eq 40 ]] && { echo "❌ PostgreSQL primario no respondió"; exit 1; }
done
echo "  ✔ primario listo; levantando standby (replicación)…"
${COMPOSE} up -d pg-standby

echo "▶ [5/8] Root CA…"
${COMPOSE} up -d stepca-root
wait_health "https://localhost:${ROOT_PORT:-9000}/health" 40 || { echo "❌ Root no respondió"; exit 1; }
echo "  ✔ Root sana"

echo "▶ [6/8] Intermediate CA (2 réplicas) + HAProxy…"
${COMPOSE} up -d --force-recreate stepca-int-1
sleep 8   # deja que la réplica 1 copie cert/clave al volumen compartido
${COMPOSE} up -d --force-recreate stepca-int-2
${COMPOSE} up -d --force-recreate haproxy
wait_health "https://localhost:${INT_PORT}/health" 40 || { echo "❌ Intermediate (LB) no respondió"; ${COMPOSE} logs --tail=20 stepca-int-1; exit 1; }
echo "  ✔ Intermediate sana detrás del balanceador"

echo "▶ [7/8] Fingerprint de la Root y config de la RA (PostgreSQL)…"
FP="$(docker exec stepca-root step certificate fingerprint /home/step/certs/root_ca.crt | tr -d '\r\n')"
cp -f persistent/root/certs/root_ca.crt          "${RA_DIR}/certs/" 2>/dev/null || true
cp -f persistent/intermediate/certs/intermediate_ca.crt "${RA_DIR}/certs/" 2>/dev/null || true
cat > "${RA_DIR}/config/ca.json" <<EOF
{
  "address": ":9100",
  "dnsNames": ["stepca-ra-one.local","localhost"],
  "db": {"type": "postgresql", "dataSource": "${DSN_RA}"},
  "logger": {"format": "text"},
  "authority": {
    "type": "stepcas",
    "certificateAuthority": "https://stepca-intermediate:9000",
    "certificateAuthorityFingerprint": "${FP}",
    "certificateIssuer": { "type": "jwk", "provisioner": "ra_jwk", "key": "/home/step/secrets/ra.key.pem" },
    "provisioners": [
      { "type": "ACME", "name": "acme-http", "challenges": ["http-01"],
        "policy": { "x509": { "allow": { "dns": ["*.local"] }, "allowWildcardNames": false } } },
      { "type": "ACME", "name": "acme-dns", "challenges": ["dns-01"],
        "policy": { "x509": { "allow": { "dns": ["*.local","*.test"] }, "allowWildcardNames": true } } },
      { "type": "ACME", "name": "acme-tls", "challenges": ["tls-alpn-01"],
        "policy": { "x509": { "allow": { "dns": ["*.local"] }, "allowWildcardNames": false } } },
      { "type": "ACME", "name": "acme-device", "challenges": ["device-attest-01"],
        "attestationFormats": ["step","tpm","apple"],
        "policy": { "x509": { "allow": { "dns": ["*.local"], "permanentIdentifier": ["*"] } } } }
    ]
  },
  "tls": { "cipherSuites": ["TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305","TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256"],
           "minVersion": 1.2, "maxVersion": 1.3, "renegotiation": false }
}
EOF

echo "▶ [8/8] RA (2 réplicas) + observabilidad + UI…"
${COMPOSE} up -d --force-recreate stepca-ra-1 stepca-ra-2
${COMPOSE} up -d --build prometheus grafana stepca-ui
wait_health "https://localhost:${RA_PORT}/health" 50 || { echo "❌ RA (LB) no respondió"; ${COMPOSE} logs --tail=20 stepca-ra-1; exit 1; }

echo "✅ Stack HA completo: PostgreSQL + 2×Intermediate + 2×RA tras HAProxy + Prometheus/Grafana + UI."
echo "   Intermediate LB: https://localhost:${INT_PORT}   RA LB: https://localhost:${RA_PORT}"
echo "   HAProxy stats: http://localhost:$(envval HAPROXY_STATS_PORT || echo 8404)   UI: http://localhost:$(envval UI_PORT || echo 8088)"
