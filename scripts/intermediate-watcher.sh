#!/usr/bin/env bash
# Watcher del host para el autodespliegue de intermedias pedidas desde la UI.
#
# La UI (que NO monta el socket de Docker) encola pedidos en persistent/ui/spool/.
# Este script —que SÍ corre en el host con acceso a Docker— los toma y despliega:
#   add-intermediate.sh  ->  docker compose up -d stepca-int-<id>  ->  recrea la UI
# para que la nueva intermedia se registre como emisora y aparezca en el tablero Estado.
#
# Uso:
#   scripts/intermediate-watcher.sh           # procesa los pendientes y termina
#   scripts/intermediate-watcher.sh --loop    # se queda observando (cada 5s)
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"; cd "${ROOT_DIR}"
SPOOL="persistent/ui/spool"
mkdir -p "${SPOOL}"

overlays(){ local o=""; for f in compose.int-*.yaml; do [ -e "$f" ] && o="$o -f $f"; done; echo "$o"; }

deploy_one(){
  local reqf="$1" id name port with_ra
  id="$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["id"])' "$reqf")"
  name="$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["name"])' "$reqf")"
  port="$(python -c 'import json,sys;print(json.load(open(sys.argv[1]))["port"])' "$reqf")"
  with_ra="$(python -c 'import json,sys;print(json.load(open(sys.argv[1])).get("with_ra",False))' "$reqf")"
  local work="${SPOOL}/${id}.working.json"; mv -f "$reqf" "$work"
  echo "▶ Desplegando intermedia '${id}' (${name}) puerto ${port}…"
  local detail=""
  if bash scripts/add-intermediate.sh "$id" "$name" "$port" \
       && docker compose -f compose.yaml $(overlays) up -d "stepca-int-${id}" \
       && docker compose -f compose.yaml $(overlays) up -d stepca-ui; then
    [ "$with_ra" = "True" ] && detail="intermedia OK · RA opcional: aún no automatizada (queda como follow-up)"
    detail="${detail:-desplegada y registrada en la UI}"
    python -c 'import json,sys;d=json.load(open(sys.argv[1]));d["detail"]=sys.argv[2];json.dump(d,open(sys.argv[3],"w"))' \
      "$work" "$detail" "${SPOOL}/${id}.done.json"
    rm -f "$work"; echo "✅ '${id}' desplegada."
  else
    python -c 'import json,sys;d=json.load(open(sys.argv[1]));d["detail"]="fallo el despliegue (ver logs)";json.dump(d,open(sys.argv[2],"w"))' \
      "$work" "${SPOOL}/${id}.error.json"
    rm -f "$work"; echo "❌ '${id}' falló."
  fi
}

process(){
  shopt -s nullglob
  for reqf in "${SPOOL}"/*.request.json; do deploy_one "$reqf"; done
}

if [ "${1:-}" = "--loop" ]; then
  echo "👀 Observando ${SPOOL} (Ctrl-C para salir)…"
  while true; do process; sleep 5; done
else
  process
  echo "Listo. (usá --loop para observar continuamente)"
fi
