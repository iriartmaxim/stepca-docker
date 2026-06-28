# ROADMAP — UI / PKI (trabajo autónomo)

Estado por ítem: ⬜ pendiente · 🚧 en curso · ✅ hecho. Lo mantiene la tarea
programada `stepca-ui-features` (cada ~10 h) y el trabajo manual.

## Ideas principales

### 1. Paridad UI ↔ scripts/  🚧
Llevar a la UI las operaciones de `scripts/` (gated por `UI_TOKEN`), ejecutando vía
API de step-ca / SQL lo que se pueda, y exponiendo comando/guía lo que requiera el
socket de Docker (manteniendo UI-sin-socket).
- ✅ Sección "Operaciones": catálogo (/api/operations) con comando copiable + descripción
  (backup, backup-pg, restore, pg-status, pg-failover, add/import-intermediate, renew,
  smoke, gen-secrets). Las de host se ejecutan en la máquina (UI sin socket).
- 🚧 Ejecutables vía API desde la UI (gated por token): ✅ revocación; pg-status en vivo,
  smoke desde el backend.

### 2. CSR de sub-CA + firma con CA externa (Microsoft ADCS)  ✅ (núcleo)
- ✅ "Generar CSR" con **perfil sub-CA** (CA:true, pathlen, keyCertSign+cRLSign,
  RSA 4096) — toggle en la UI (modo hoja / sub-CA).
- ✅ **Importar cadena firmada**: `scripts/import-intermediate.sh` crea una intermedia
  externa operativa (cadena externa = ancla, DB, provisioner web, registro como emisora).
  Probado con CA externa simulada (emite encadenando a la Root externa).
- ✅ Doc: `docs/external-ca-adcs.md` (alcances/duración/EKU de sub-CA y flujo ADCS).
- ⬜ Follow-up: endpoint de la UI para *subir* el cert/cadena firmados y stagearlos
  (la puesta en marcha sigue siendo acción de host, por el principio UI-sin-socket).

### 3. Intermedias como ACME + gestión desde la UI  ✅
- ✅ Gestión de provisioners (alta/baja ACME) vía Admin API (ya en `e99cc2c`).
- ✅ Sumar provisioners ACME a **cualquier** intermedia (principal, multi-intermediate, ADCS):
  add/remove por-emisora (`issuer`), usando la credencial `web` de esa CA.
- ✅ /api/provisioners lista todas las CAs (incl. int-b/int-c); selector de intermedia en la UI.

### 4. Seccionar el apartado Estado  ✅
- ✅ Subsecciones: CAs · Réplicas+HAProxy · PostgreSQL · Observabilidad.
- ✅ Datos en vivo: HAProxy stats (CSV, /api/haproxy), replicación de Postgres
  (/api/pg-status con psycopg2), links a Grafana/Prometheus/Targets.

### 5. Sección Configuración en la UI  🚧
- ✅ Lectura: sección Configuración + /api/settings (UI/emisión, claims y provisioners
  de la intermedia, infra Postgres/HAProxy). La UI monta la config de la intermedia ro.
- ⬜ Edición aplicable donde sea seguro (umbrales UI, claims, políticas).

## Mejoras (post-5)
- ⬜ Performance: pooling/índices Postgres, tuning step-ca, caché UI, recarga de
  provisioners entre réplicas (lag de caché HA).
- ⬜ Operaciones: revocación CRL/OCSP, rotación de intermedias, exportaciones, renovación auto.
- ⬜ Configuración: más parámetros editables, perfiles de despliegue.

## Bitácora
- (init) ROADMAP creado; arranque del ítem #4 (seccionar Estado).
- #4 ✅ Estado seccionado (CAs/HAProxy/PostgreSQL/Observabilidad) con datos en vivo.
- #2 ✅ (núcleo) CSR sub-CA en la UI + import-intermediate.sh (firma ADCS) + doc.
  Probado con CA externa simulada. Próximo: #5 (Configuración) o #1 (operaciones).

- #5 🚧 Sección Configuración (lectura): /api/settings + sección en la UI.
- #1 🚧 Sección Operaciones (catálogo de comandos, /api/operations). Falta ejecución vía API/SQL.
- #3 ✅ Gestión de provisioners por-emisora (cualquier intermedia, incl. ADCS).
- ops ✅ Descarga de certificados del inventario (/api/cert-file, validado).
- ops ✅ Inspección de certificados del inventario (/api/cert-inspect: EKU/KeyUsage/etc.).
- #1 ✅ Revocación de certificados desde la UI (/api/revoke, token JWK web).
