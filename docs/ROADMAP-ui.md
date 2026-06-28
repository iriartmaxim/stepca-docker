# ROADMAP — UI / PKI (trabajo autónomo)

Estado por ítem: ⬜ pendiente · 🚧 en curso · ✅ hecho. Lo mantiene la tarea
programada `stepca-ui-features` (cada ~10 h) y el trabajo manual.

## Ideas principales

### 1. Paridad UI ↔ scripts/
Llevar a la UI las operaciones de `scripts/` (gated por `UI_TOKEN`), ejecutando vía
API de step-ca / SQL lo que se pueda, y exponiendo comando/guía lo que requiera el
socket de Docker (manteniendo UI-sin-socket).
- ⬜ Sección "Operaciones" en la UI.
- ⬜ backup-pg / pg-status / pg-failover (vía SQL/endpoints).
- ⬜ smoke-test / renew / gen-secrets / add-intermediate (guía o ejecución segura).

### 2. CSR de sub-CA + firma con CA externa (Microsoft ADCS)
- ⬜ "Generar CSR" con **perfil sub-CA**: basicConstraints CA:true (pathlen),
  KeyUsage keyCertSign+cRLSign, duración/tamaño configurables.
- ⬜ **Importar cadena firmada** (cert intermedio de ADCS + cadena) y crear una
  intermedia "externa" operativa (config, DB, provisioner web, registro como emisora).
- ⬜ Doc: alcances/duración/EKU de sub-CA y flujo ADCS.

### 3. Intermedias como ACME + gestión desde la UI
- ✅ Gestión de provisioners (alta/baja ACME) vía Admin API (ya en `e99cc2c`).
- ⬜ Sumar provisioners ACME a cualquier intermedia (incl. multi-intermediate / ADCS).
- ⬜ Selección de emisora + estado de provisioners por CA en la UI.

### 4. Seccionar el apartado Estado  ✅
- ✅ Subsecciones: CAs · Réplicas+HAProxy · PostgreSQL · Observabilidad.
- ✅ Datos en vivo: HAProxy stats (CSV, /api/haproxy), replicación de Postgres
  (/api/pg-status con psycopg2), links a Grafana/Prometheus/Targets.

### 5. Sección Configuración en la UI
- ⬜ Lectura de toda la config (.env, claims/duraciones, políticas, Postgres/HAProxy,
  umbrales UI).
- ⬜ Edición aplicable donde sea seguro.

## Mejoras (post-5)
- ⬜ Performance: pooling/índices Postgres, tuning step-ca, caché UI, recarga de
  provisioners entre réplicas (lag de caché HA).
- ⬜ Operaciones: revocación CRL/OCSP, rotación de intermedias, exportaciones, renovación auto.
- ⬜ Configuración: más parámetros editables, perfiles de despliegue.

## Bitácora
- (init) ROADMAP creado; arranque del ítem #4 (seccionar Estado).
- #4 ✅ Estado seccionado (CAs/HAProxy/PostgreSQL/Observabilidad) con datos en vivo.
  Próximo: #2 (CSR sub-CA + import ADCS) — el de mayor alcance.
