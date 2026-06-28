#!/bin/sh
# Entrypoint del contenedor de demo device-attest-01.
#  - inicializa el estado del TPM con un EK + certificado de EK (CA local swtpm)
#  - levanta swtpm como dispositivo CUSE /dev/tpm0
#  - deja el contenedor vivo para ejecutar el flujo de atestación
set -e

STATE=/tpmstate
mkdir -p "$STATE"

echo "[swtpm] Inicializando estado TPM + EK cert…"
swtpm_setup --tpm2 --tpmstate "$STATE" \
  --create-ek-cert --create-platform-cert --overwrite --display 2>&1 | tail -5 || true

echo "[swtpm] Levantando CUSE /dev/tpm0…"
swtpm cuse -n tpm0 --tpm2 --tpmstate "dir=$STATE" --flags startup-clear &
sleep 2
ls -l /dev/tpm* 2>&1 || echo "(no aparecieron nodos /dev/tpm*)"

# Exportar la raíz de la CA local del EK (para attestationRoots de step-ca)
if [ -f /var/lib/swtpm-localca/swtpm-localca-rootca-cert.pem ]; then
  cp /var/lib/swtpm-localca/swtpm-localca-rootca-cert.pem /tpmstate/ek-rootca.pem
  echo "[swtpm] Raíz EK exportada en /tpmstate/ek-rootca.pem"
fi

echo "[swtpm] Listo. Contenedor en espera."
exec sleep infinity
