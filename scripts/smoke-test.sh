#!/usr/bin/env bash
# Smoke test end-to-end: verifica que las 3 CAs responden /health.
set -euo pipefail

ROOT_PORT="${ROOT_PORT:-9000}"
INTERMEDIATE_PORT="${INTERMEDIATE_PORT:-9001}"
RA_PORT="${RA_PORT:-9100}"

check() {
  local name="$1" url="$2"
  printf "→ %-24s %s ... " "$name" "$url"
  if curl -sfk --max-time 5 "$url" >/dev/null; then
    echo "OK ✅"
  else
    echo "FALLA ❌"; return 1
  fi
}

rc=0
check "Root CA"         "https://localhost:${ROOT_PORT}/health"         || rc=1
check "Intermediate CA" "https://localhost:${INTERMEDIATE_PORT}/health" || rc=1
check "Registration Auth" "https://localhost:${RA_PORT}/health"         || rc=1

if [[ $rc -eq 0 ]]; then
  echo "✅ Smoke test OK: las 3 CAs responden."
else
  echo "❌ Smoke test con fallos. Revisá 'make logs'." >&2
fi
exit $rc
