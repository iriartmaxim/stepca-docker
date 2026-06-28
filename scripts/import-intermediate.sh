#!/usr/bin/env bash
# Importa una CA intermedia firmada por una CA EXTERNA (p. ej. Microsoft ADCS).
# Flujo: generás el CSR de sub-CA en la UI ("Generar CSR" → modo CA intermedia),
# lo firmás con ADCS (plantilla "Subordinate Certification Authority"), y con
# este script importás el cert firmado + la cadena externa + la clave para crear
# una intermedia operativa (config, DB, provisioner 'web', alias, registro en la UI).
#
# Uso: scripts/import-intermediate.sh <id> "<Nombre>" <cert-firmado> <cadena> <clave> [puerto]
#   <cert-firmado>: PEM del cert intermedio firmado por la CA externa.
#   <cadena>:       PEM de la cadena externa (issuing CA + root) = ancla de confianza.
#   <clave>:        PEM de la clave privada de la sub-CA (la que generaste con el CSR).
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

ID="${1:?Falta <id>}"; NAME="${2:?Falta <nombre>}"; CERT="${3:?Falta cert firmado}"
CHAIN="${4:?Falta cadena}"; KEY="${5:?Falta clave}"; PORT="${6:-9003}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"; cd "${ROOT_DIR}"
for f in "$CERT" "$CHAIN" "$KEY"; do [[ -f "$f" ]] || { echo "❌ No existe: $f"; exit 1; }; done
envval(){ grep -E "^$1=" .env 2>/dev/null|head -1|cut -d= -f2-|sed 's/[[:space:]]*#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//'; }
IMAGE="$(envval STEPCA_IMAGE)"; IMAGE="${IMAGE:-smallstep/step-ca:0.28.3}"
PG_USER="$(envval PG_USER)"; PG_USER="${PG_USER:-stepca}"
PG_PASSWORD="$(envval PG_PASSWORD)"; PG_PASSWORD="${PG_PASSWORD:-stepca-change-me}"
SUBCA_PW="secrets/intermediate_ca_password.txt"
DIR="persistent/intermediate-${ID}"; DB="stepca_int_${ID}"
DSN="postgresql://${PG_USER}:${PG_PASSWORD}@pg-primary:5432,pg-standby:5432/${DB}?target_session_attrs=read-write&sslmode=disable"
mkdir -p "${DIR}"/{certs,secrets,config}

echo "▶ [1/4] Importando cert/cadena y cifrando la clave…"
cp -f "$CERT"  "${DIR}/certs/intermediate_ca.crt"
cp -f "$CHAIN" "${DIR}/certs/root_ca.crt"     # ancla de confianza = cadena externa
# Cifrar la clave (viene sin password de la UI) con el password de intermedia
docker run --rm -v "${ROOT_DIR}/${KEY}:/in.key:ro" -v "${ROOT_DIR}/${SUBCA_PW}:/pw:ro" \
  -v "${ROOT_DIR}/${DIR}/secrets:/out" --entrypoint sh "${IMAGE}" -c '
    : > /tmp/empty
    step crypto change-pass /in.key --out /out/intermediate_ca_key --password-file /tmp/empty --new-password-file /pw --force >/dev/null 2>&1'
[[ -s "${DIR}/secrets/intermediate_ca_key" ]] || { echo "❌ No se pudo cifrar la clave"; exit 1; }

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
WEB_PUB="$(printf '%s\n' "${WGEN}"|sed -n '/===PUB===/,/===EK===/p'|sed '1d;$d')"
WEB_EK="$(printf '%s\n' "${WGEN}"|sed -n '/===EK===/,$p'|sed '1d'|tr -d '\n')"

echo "▶ [3/4] Base de datos ${DB} y config…"
docker exec pg-primary psql -U "${PG_USER}" -tAc "SELECT 1 FROM pg_database WHERE datname='${DB}'" 2>/dev/null|grep -q 1 \
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
  "crl": { "enabled": true, "generateOnRevoke": true, "cacheDuration": "12h" },
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

echo "▶ [4/4] Overlay compose + registro en la UI…"
cat > "compose.int-${ID}.yaml" <<EOF
# Intermedia IMPORTADA '${ID}' (firmada por CA externa). Uso:
#   docker compose -f compose.yaml -f compose.int-${ID}.yaml up -d stepca-int-${ID}
services:
  stepca-int-${ID}:
    image: ${IMAGE}
    container_name: stepca-int-${ID}
    restart: unless-stopped
    depends_on: { pg-primary: { condition: service_healthy } }
    secrets: [ { source: intermediate_ca_password, target: subca_password } ]
    networks: { default: { aliases: [ "stepca-intermediate-${ID}" ] } }
    volumes:
      - ./${DIR}/certs:/home/step/certs
      - ./${DIR}/config:/home/step/config
      - ./${DIR}/secrets:/home/step/secrets
      - ./infra/stepca/templates:/home/step/templates:ro
    command: sh -c "step-ca --password-file=/run/secrets/subca_password /home/step/config/ca.json"
    healthcheck:
      test: ["CMD","step","ca","health","--ca-url","https://localhost:9000","--root","/home/step/certs/root_ca.crt"]
      interval: 10s
      timeout: 5s
      retries: 12
    ports: [ "${PORT}:9000" ]
  stepca-ui:
    environment:
      ISSUER_${ID^^}: "${NAME}|https://stepca-intermediate-${ID}:9000|/run/secrets/web_${ID}"
    volumes:
      - ./${DIR}/web_provisioner_password:/run/secrets/web_${ID}:ro
EOF

echo "✅ Intermedia importada '${ID}' lista (firmada por CA externa)."
echo "   Levantala: docker compose -f compose.yaml -f compose.int-${ID}.yaml up -d stepca-int-${ID} stepca-ui"
echo "   Endpoint:  https://localhost:${PORT}  ·  ancla de confianza: la cadena externa importada"
