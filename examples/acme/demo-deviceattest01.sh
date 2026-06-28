#!/usr/bin/env bash
# Demo end-to-end del challenge ACME device-attest-01 con TPM por software (swtpm).
#
# Flujo (en un host con soporte de TPM):
#   1. Construye la imagen swtpm+step (examples/acme/deviceattest/).
#   2. Levanta el TPM emulado y obtiene un /dev/tpmrm0 (vía vtpm-proxy o CUSE).
#   3. Toma la raíz de la CA del EK del swtpm y la registra en attestationRoots
#      del provisioner acme-device de la RA; reinicia la RA.
#   4. En el dispositivo: crea una AK en el TPM, una clave atestiguada, y pide el
#      certificado por device-attest-01.
#
# REQUISITO DE ENTORNO: el cliente `step` (tpmkms) necesita un ARCHIVO de
# dispositivo TPM (/dev/tpmrm0 o /dev/tpm0). Para emular sin hardware hace falta
# UNO de:
#   - módulo kernel `tpm_vtpm_proxy` (aporta /dev/vtpmx)  -> swtpm chardev --vtpm-proxy
#   - swtpm compilado con CUSE                            -> swtpm cuse
#   - un TPM real pasado al contenedor (--device /dev/tpmrm0)
# Docker Desktop / WSL2 NO trae vtpm-proxy ni CUSE: en ese caso este demo se
# detiene con un mensaje claro (la config de la RA es correcta igual).
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"
NAME="stepca-deviceattest"
IMG="stepca-deviceattest:latest"
NET="$(docker inspect stepca-ra-one.local -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' | head -1)"

echo "▶ [1/4] Construyendo imagen swtpm+step…"
docker build -q -t "${IMG}" examples/acme/deviceattest >/dev/null

echo "▶ [2/4] Levantando TPM emulado…"
docker rm -f "${NAME}" >/dev/null 2>&1 || true
docker run -d --name "${NAME}" --privileged --network "${NET}" "${IMG}" >/dev/null
sleep 5

if ! docker exec "${NAME}" sh -c 'ls /dev/tpmrm0 /dev/tpm0 2>/dev/null' >/dev/null 2>&1; then
  echo "❌ No hay dispositivo TPM disponible en este host."
  docker exec "${NAME}" sh -c 'ls -l /dev/vtpmx 2>&1 || true; swtpm --version | head -1' 2>&1 | sed 's/^/   /'
  echo "   Este entorno (Docker Desktop/WSL2) no expone vtpm-proxy ni CUSE."
  echo "   En un host Linux con TPM real o con el módulo tpm_vtpm_proxy, este"
  echo "   demo completa la emisión. La config de la RA (provisioner acme-device)"
  echo "   ya está activa y es correcta. Ver docs/acme-challenges.md."
  docker rm -f "${NAME}" >/dev/null 2>&1 || true
  exit 2
fi

echo "▶ [3/4] Registrando la raíz del EK en el provisioner acme-device…"
docker cp "${NAME}:/tpmstate/ek-rootca.pem" persistent/ra/ra-one/certs/ek-rootca.pem
python - "$PWD/persistent/ra/ra-one/config/ca.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p))
for pr in d["authority"]["provisioners"]:
    if pr.get("name")=="acme-device":
        pr["attestationRoots"]="/home/step/certs/ek-rootca.pem"
json.dump(d,open(p,"w"),indent=2)
print("attestationRoots configurado")
PY
docker compose up -d --force-recreate stepca-ra-one.local >/dev/null
until curl -sfk --max-time 3 https://localhost:9100/health >/dev/null 2>&1; do sleep 2; done

echo "▶ [4/4] Atestación y emisión del certificado…"
docker exec "${NAME}" sh -c '
  step kms create "tpmkms:name=device-ak;ak=true" 2>&1 | tail -1
  step ca certificate "device-001" /tmp/dev.crt /tmp/dev.key \
    --provisioner acme-device \
    --ca-url https://stepca-ra-one.local:9100 \
    --kms "tpmkms:" --attestation-uri "tpmkms:name=device-ak" \
    --root /tpmstate/ek-rootca.pem 2>&1 | tail -8
  step certificate inspect /tmp/dev.crt --short 2>/dev/null
'
docker rm -f "${NAME}" >/dev/null 2>&1 || true
echo "✅ Demo device-attest-01 finalizado"
