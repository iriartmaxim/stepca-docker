#!/usr/bin/env bash
# Orquesta el despliegue completo de la PKI SIN pasos manuales ni Ansible:
#   1. genera secretos
#   2. genera el par de claves del provisioner ra_jwk (idempotente)
#   3. escribe la config de la intermedia con el provisioner ra_jwk embebido
#   4. levanta Root + Intermediate y espera a que estén sanas
#   5. calcula el fingerprint de la Root y escribe la config de la RA
#   6. levanta la RA
set -euo pipefail

# En Git Bash/MSYS (Windows), evita que se conviertan rutas tipo /home/... que
# pasamos a `docker exec` (no-op en Linux real).
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# Imagen (respeta .env si existe)
IMAGE="$(grep -E '^STEPCA_IMAGE=' .env 2>/dev/null | cut -d= -f2-)"
IMAGE="${IMAGE:-smallstep/step-ca:0.28.3}"
COMPOSE="docker compose"

INT_CFG="persistent/intermediate/config/ca.json"
RA_DIR="persistent/ra/ra-one"
RA_KEY="${RA_DIR}/secrets/ra.key.pem"
RA_PUB="${RA_DIR}/secrets/ra_jwk.pub.json"

echo "▶ [1/6] Secretos…"
bash scripts/gen-secrets.sh

echo "▶ [2/6] Estructura de carpetas…"
mkdir -p persistent/root/{config,certs,secrets} \
         persistent/intermediate/{config,certs,secrets,db} \
         persistent/tmp "${RA_DIR}"/{config,certs,secrets,db}

echo "▶ [3/6] Par de claves del provisioner ra_jwk…"
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
  echo "  ✔ ra.key.pem y clave pública generadas"
else
  echo "  ⏭ ya existen (reutilizando)"
fi
PUBJWK="$(cat "${RA_PUB}")"

echo "▶ [3b] Config de la Intermediate CA (con provisioner ra_jwk)…"
cat > "${INT_CFG}" <<EOF
{
  "root": "/home/step/certs/root_ca.crt",
  "crt":  "/home/step/certs/intermediate_ca.crt",
  "key":  "/home/step/secrets/intermediate_ca_key",
  "address": ":9000",
  "dnsNames": ["stepca-intermediate","localhost"],
  "logger": {"format": "text"},
  "db": {"type": "badgerv2", "dataSource": "/home/step/db"},
  "authority": {
    "enableAdmin": false,
    "claims": {
      "minTLSCertDuration": "5m",
      "maxTLSCertDuration": "24h",
      "defaultTLSCertDuration": "24h"
    },
    "provisioners": [
      { "type": "JWK", "name": "ra_jwk", "key": ${PUBJWK} }
    ]
  }
}
EOF

echo "▶ [4/6] Levantando Root + Intermediate…"
${COMPOSE} up -d stepca-root
# --force-recreate: recarga la config si cambió en una re-ejecución (la DB persiste en su volumen)
${COMPOSE} up -d --force-recreate stepca-intermediate

echo "  ⏳ esperando salud de la Intermediate…"
for i in $(seq 1 30); do
  if curl -sfk --max-time 3 "https://localhost:${INTERMEDIATE_PORT:-9001}/health" >/dev/null; then
    echo "  ✔ Intermediate sana"; break
  fi
  sleep 3
  [[ $i -eq 30 ]] && { echo "❌ Intermediate no respondió"; ${COMPOSE} logs stepca-intermediate | tail -20; exit 1; }
done

echo "▶ [5/6] Fingerprint de la Root y config de la RA…"
FP="$(docker exec stepca-root step certificate fingerprint /home/step/certs/root_ca.crt | tr -d '\r\n')"
echo "  ✔ fingerprint: ${FP}"
# Certs de confianza para la RA (healthcheck y cadena)
cp -f persistent/root/certs/root_ca.crt          "${RA_DIR}/certs/" 2>/dev/null || true
cp -f persistent/intermediate/certs/intermediate_ca.crt "${RA_DIR}/certs/" 2>/dev/null || true

cat > "${RA_DIR}/config/ca.json" <<EOF
{
  "address": ":9100",
  "dnsNames": ["stepca-ra-one.local"],
  "db": {"type": "badgerv2", "dataSource": "/home/step/db"},
  "logger": {"format": "text"},
  "authority": {
    "type": "stepcas",
    "certificateAuthority": "https://stepca-intermediate:9000",
    "certificateAuthorityFingerprint": "${FP}",
    "certificateIssuer": {
      "type": "jwk",
      "provisioner": "ra_jwk",
      "key": "/home/step/secrets/ra.key.pem"
    },
    "provisioners": [
      { "type": "ACME", "name": "acme-http", "challenges": ["http-01"],
        "policy": { "x509": { "allow": { "dns": ["*.local"] }, "allowWildcardNames": false } } },
      { "type": "ACME", "name": "acme-dns", "challenges": ["dns-01"],
        "policy": { "x509": { "allow": { "dns": ["*.local"] }, "allowWildcardNames": true } } },
      { "type": "ACME", "name": "acme-tls", "challenges": ["tls-alpn-01"],
        "policy": { "x509": { "allow": { "dns": ["*.local"] }, "allowWildcardNames": false } } },
      { "type": "ACME", "name": "acme-device", "challenges": ["device-attest-01"],
        "attestationFormats": ["step","tpm","apple"],
        "policy": { "x509": { "allow": { "dns": ["*.local"], "permanentIdentifier": ["*"] } } } }
    ]
  },
  "tls": {
    "cipherSuites": ["TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305","TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256"],
    "minVersion": 1.2, "maxVersion": 1.3, "renegotiation": false
  }
}
EOF

echo "▶ [6/6] Levantando la RA…"
${COMPOSE} up -d --force-recreate stepca-ra-one.local

echo "  ⏳ esperando salud de la RA…"
for i in $(seq 1 30); do
  if curl -sfk --max-time 3 "https://localhost:${RA_PORT:-9100}/health" >/dev/null; then
    echo "✅ Stack completo: Root + Intermediate + RA sanas."
    exit 0
  fi
  sleep 3
done
echo "❌ La RA no respondió a tiempo"; ${COMPOSE} logs stepca-ra-one.local | tail -20; exit 1
