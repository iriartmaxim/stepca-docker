#!/usr/bin/env bash
set -eo pipefail

#############################################
# Parámetros (ajusta si tu ruta cambia)
#############################################
WORKDIR="/root/stepca/stepca-try1"
INTER_PASS="$WORKDIR/secrets/intermediate_ca_password.txt"
RA_SECRETS_DIR="$WORKDIR/persistent/ra/ra-one/secrets"

#############################################
# Temporales y limpieza automática
#############################################
TMP_JSON="$(mktemp)"
TMP_JWK="$(mktemp)"
trap 'rm -f "$TMP_JSON" "$TMP_JWK"' EXIT

#############################################
# 1) Crear carpeta de destino
#############################################
mkdir -p "$RA_SECRETS_DIR"

#############################################
# 2) Volcar listado de provisioners
#############################################
docker exec stepca-intermediate \
  step ca provisioner list \
    --ca-url https://stepca-intermediate:9000/ \
  > "$TMP_JSON"

#############################################
# 3) Extraer el encryptedKey JWK
#############################################
jq -r '.[] | select(.name=="ra_jwk") | .encryptedKey' "$TMP_JSON" \
  > "$TMP_JWK"



#############################################
# 4) Reencriptar a PEM PKCS#8 (sin interacción)
#############################################
echo "🔐 Reencriptando JWK para la RA…"
yes y | step crypto key format "$TMP_JWK" \
     --pem --pkcs8 \
     --password-file "$INTER_PASS" \
     --out "$RA_SECRETS_DIR/ra.key.pem" \
     --force \
     --insecure \
     --no-password  2>/dev/null || true

echo "✅ ra.key.pem generado en $RA_SECRETS_DIR"

