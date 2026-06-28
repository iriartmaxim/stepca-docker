#!/usr/bin/env bash
# Scaffold del challenge ACME device-attest-01 con un TPM por software (swtpm).
#
# device-attest-01 NO usa control de red (http/dns/tls): el dispositivo prueba su
# identidad con una clave ATESTIGUADA por hardware (TPM 2.0, Apple SE o el agente
# de Smallstep). El SAN emitido es un `permanentIdentifier` (p. ej. el serial),
# no un nombre DNS.
#
# Este script levanta un TPM emulado (swtpm) y muestra el flujo. Para que step-ca
# ACEPTE la atestación, su provisioner acme-device debe confiar en la cadena del
# EK del TPM (campo "attestationRoots" con el CA del fabricante / del emulador).
# Con swtpm el EK es de prueba, así que hay que registrar su raíz en el provisioner.
#
# Requisitos: imagen con swtpm + tpm2-tools + step (no incluida por defecto).
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

cat <<'DOC'
─────────────────────────────────────────────────────────────────────────────
 device-attest-01 — flujo de referencia
─────────────────────────────────────────────────────────────────────────────
 1) TPM por software (swtpm) — provee /dev/tpm0 emulado:
      docker run -d --name swtpm \
        --network stepca-docker_acme-demo \
        tpm2software/swtpm \
        swtpm socket --tpm2 --server type=tcp,port=2321 \
          --ctrl type=tcp,port=2322 --flags not-need-init

 2) Cliente con step + tpm2-tools apuntando al swtpm:
      export TPM2TOOLS_TCTI="swtpm:host=swtpm,port=2321"
      # Generar/atestiguar la clave del dispositivo en el TPM (tpmkms)
      step kms create --kms 'tpmkms:' 'tpmkms:name=device-ak;ak=true'

 3) Solicitar el certificado por device-attest-01:
      step ca certificate "$(hostname)" dev.crt dev.key \
        --provisioner acme-device \
        --ca-url https://stepca-ra-one.local:9100 \
        --kms 'tpmkms:' \
        --attestation-uri 'tpmkms:name=device-ak' \
        --root root_ca.crt

 4) Para que la RA acepte la atestación del TPM emulado, agregá la raíz del EK
    del swtpm al provisioner acme-device en el ca.json de la RA:
      { "type":"ACME", "name":"acme-device", "challenges":["device-attest-01"],
        "attestationFormats":["tpm"],
        "attestationRoots":"<contenido PEM del CA del EK del swtpm>" }
─────────────────────────────────────────────────────────────────────────────
 NOTA: a diferencia de http/dns/tls, este caso depende de hardware de atestación
 (o un emulador con su cadena de EK). El provisioner ya está activo en la RA; lo
 que falta es la cadena de confianza del EK, específica de cada TPM/fabricante.
─────────────────────────────────────────────────────────────────────────────
DOC
