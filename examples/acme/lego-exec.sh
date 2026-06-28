#!/bin/sh
# Hook 'exec' de lego para el challenge dns-01.
# lego lo invoca como:  lego-exec.sh present|cleanup <fqdn> <valor-TXT>
# Escribe el registro TXT _acme-challenge.* en la zona "test" que sirve CoreDNS
# (volumen compartido /zones) y regenera el archivo con un serial nuevo.
# Se usa .test (no .local) porque .local es mDNS y rompe la validación dns-01.
set -e

ZONE_DIR=/zones
ZONE="${ZONE_DIR}/db.test"
RECORDS="${ZONE_DIR}/records"
DNS_IP="${DNS_IP:-172.31.0.53}"

ACTION="$1"; FQDN="$2"; VALUE="$3"
# Nombre relativo a $ORIGIN test.  (_acme-challenge.demo.test. -> _acme-challenge.demo)
NAME="$(printf '%s' "$FQDN" | sed 's/\.test\.\?$//; s/\.$//')"

touch "${RECORDS}"
case "${ACTION}" in
  present)
    echo "${NAME} IN TXT \"${VALUE}\"" >> "${RECORDS}"
    ;;
  cleanup)
    grep -v "^${NAME} IN TXT" "${RECORDS}" > "${RECORDS}.tmp" 2>/dev/null || true
    mv "${RECORDS}.tmp" "${RECORDS}" 2>/dev/null || true
    ;;
esac

# Regenerar la zona con serial = epoch (fuerza el reload de CoreDNS)
SERIAL="$(date +%s)"
{
  echo '$ORIGIN test.'
  echo '$TTL 30'
  echo "@   IN SOA ns.test. admin.test. ( ${SERIAL} 7200 3600 1209600 30 )"
  echo '@   IN NS  ns.test.'
  echo "ns  IN A   ${DNS_IP}"
  cat "${RECORDS}"
} > "${ZONE}"

# Dar tiempo a CoreDNS a recargar (reload 2s)
sleep 3
