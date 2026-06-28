#!/usr/bin/env bash
# Provisiona una CA intermedia ADICIONAL (soporte multi-intermediate / "N intermedias").
# La Root firma una intermedia nueva, con su propia clave, DB, config y provisioner
# 'web' (para emitir desde la UI/CLI). Repetí el script con otro <id> para sumar más.
#
# Uso:  scripts/add-intermediate.sh <id> "<Nombre CA>" [puerto-host]
#   ej: scripts/add-intermediate.sh b "Intermediate B CA" 9002
#
# Después: agregá el servicio stepca-int-<id> al compose (patrón documentado) o usá
# el override generado, y el backend en HAProxy. Este script deja todo el material listo.
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

ID="${1:?Falta <id> (ej: b)}"
NAME="${2:?Falta el nombre de la CA}"
PORT="${3:-9002}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"; cd "${ROOT_DIR}"
envval(){ grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//'; }
IMAGE="$(envval STEPCA_IMAGE)"; IMAGE="${IMAGE:-smallstep/step-ca:0.28.3}"
PG_USER="$(envval PG_USER)"; PG_USER="${PG_USER:-stepca}"
PG_PASSWORD="$(envval PG_PASSWORD)"; PG_PASSWORD="${PG_PASSWORD:-stepca-change-me}"

DIR="persistent/intermediate-${ID}"
DB="stepca_int_${ID}"
DSN="postgresql://${PG_USER}:${PG_PASSWORD}@pg-primary:5432,pg-standby:5432/${DB}?target_session_attrs=read-write&sslmode=disable"
mkdir -p "${DIR}"/{certs,secrets,config}

echo "▶ [1/4] La Root firma la intermedia '${NAME}'…"
if [[ -f "${DIR}/certs/intermediate_ca.crt" && -f "${DIR}/secrets/intermediate_ca_key" ]]; then
  echo "  ⏭ ya existe el material de '${ID}' (reutilizando)"
else
docker exec stepca-root sh -c "
  step certificate create '${NAME}' /tmp/i-${ID}.csr /tmp/i-${ID}.key --csr --kty RSA --size 4096 --password-file /run/secrets/subca_password >/dev/null 2>&1
  ROOT=\$(step path)
  step certificate sign /tmp/i-${ID}.csr \"\$ROOT/certs/root_ca.crt\" \"\$ROOT/secrets/root_ca_key\" --profile intermediate-ca --password-file /run/secrets/ca_password > /tmp/i-${ID}.crt 2>/dev/null
"
docker cp "stepca-root:/tmp/i-${ID}.crt" "${DIR}/certs/intermediate_ca.crt"
docker cp "stepca-root:/tmp/i-${ID}.key" "${DIR}/secrets/intermediate_ca_key"
fi
cp -f persistent/root/certs/root_ca.crt "${DIR}/certs/root_ca.crt"

echo "▶ [2/4] Provisioner 'web' de esta intermedia…"
WEB_PW_FILE="${DIR}/web_provisioner_password"
[[ -f "${WEB_PW_FILE}" ]] || openssl rand -base64 24 | tr -d '\n' > "${WEB_PW_FILE}"
WEB_PW="$(cat "${WEB_PW_FILE}")"
WGEN="$(docker run --rm -e WEBPW="${WEB_PW}" --entrypoint sh "${IMAGE}" -c '
  printf "%s" "$WEBPW" > /tmp/pw
  step crypto jwk create /tmp/pub.json /tmp/key.json --kty EC --crv P-256 --password-file /tmp/pw >/dev/null 2>&1
  P=$(grep "\"protected\"" /tmp/key.json|sed "s/.*: \"\(.*\)\".*/\1/"); E=$(grep "\"encrypted_key\"" /tmp/key.json|sed "s/.*: \"\(.*\)\".*/\1/")
  IV=$(grep "\"iv\"" /tmp/key.json|sed "s/.*: \"\(.*\)\".*/\1/"); C=$(grep "\"ciphertext\"" /tmp/key.json|sed "s/.*: \"\(.*\)\".*/\1/"); T=$(grep "\"tag\"" /tmp/key.json|sed "s/.*: \"\(.*\)\".*/\1/")
  echo "===PUB==="; cat /tmp/pub.json; echo; echo "===EK==="; echo "$P.$E.$IV.$C.$T"')"
WEB_PUB="$(printf '%s\n' "${WGEN}" | sed -n '/===PUB===/,/===EK===/p' | sed '1d;$d')"
WEB_EK="$(printf '%s\n' "${WGEN}" | sed -n '/===EK===/,$p' | sed '1d' | tr -d '\n')"

echo "▶ [3/4] Base de datos ${DB} y config…"
docker exec pg-primary psql -U "${PG_USER}" -tAc "SELECT 1 FROM pg_database WHERE datname='${DB}'" 2>/dev/null | grep -q 1 \
  || docker exec pg-primary createdb -U "${PG_USER}" "${DB}"
cat > "${DIR}/config/ca.json" <<EOF
{
  "root": "/home/step/certs/root_ca.crt",
  "crt":  "/home/step/certs/intermediate_ca.crt",
  "key":  "/home/step/secrets/intermediate_ca_key",
  "address": ":9000",
  "dnsNames": ["stepca-intermediate-${ID}","localhost"],
  "logger": {"format": "text"},
  "db": {"type": "postgresql", "dataSource": "${DSN}"},
  "authority": {
    "enableAdmin": true,
    "claims": { "minTLSCertDuration": "5m", "maxTLSCertDuration": "24h", "defaultTLSCertDuration": "24h" },
    "provisioners": [
      { "type": "JWK", "name": "web", "key": ${WEB_PUB}, "encryptedKey": "${WEB_EK}",
        "policy": { "x509": { "allow": { "dns": ["*.local"] }, "allowWildcardNames": false } },
        "options": { "x509": { "templateFile": "/home/step/templates/web-leaf.tpl" } } }
    ]
  }
}
EOF

echo "▶ [4/4] Servicio compose + backend HAProxy…"
cat > "compose.int-${ID}.yaml" <<EOF
# Intermedia adicional '${ID}'. Uso:
#   docker compose -f compose.yaml -f compose.int-${ID}.yaml up -d stepca-int-${ID}
services:
  stepca-int-${ID}:
    image: ${IMAGE}
    container_name: stepca-int-${ID}
    restart: unless-stopped
    depends_on: { pg-primary: { condition: service_healthy } }
    secrets: [ { source: intermediate_ca_password, target: subca_password } ]
    networks:
      default:
        aliases: [ "stepca-intermediate-${ID}" ]
    volumes:
      - ./${DIR}/certs:/home/step/certs
      - ./${DIR}/config:/home/step/config
      - ./${DIR}/secrets:/home/step/secrets
      - ./infra/stepca/templates:/home/step/templates:ro
    command: sh -c "step-ca --password-file=/run/secrets/subca_password /home/step/config/ca.json"
    healthcheck:
      test: ["CMD","step","ca","health","--ca-url","https://localhost:9000"]
      interval: 10s
      timeout: 5s
      retries: 12
    ports: [ "${PORT}:9000" ]

  # Registra esta intermedia como CA emisora en la UI
  stepca-ui:
    environment:
      ISSUER_${ID^^}: "${NAME}|https://stepca-intermediate-${ID}:9000|/run/secrets/web_${ID}"
    volumes:
      - ./${DIR}/web_provisioner_password:/run/secrets/web_${ID}:ro
EOF

echo "✅ Intermedia '${ID}' lista: material en ${DIR}, DB ${DB}, compose.int-${ID}.yaml."
echo "   Levantala:  docker compose -f compose.yaml -f compose.int-${ID}.yaml up -d stepca-int-${ID}"
echo "   Endpoint:   https://localhost:${PORT}"
