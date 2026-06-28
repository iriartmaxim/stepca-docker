# ROADMAP — NIST hardening + features de PKI (todo gestionable desde la UI)

Principio rector: **cada feature debe ser EJECUTABLE desde la UI** (como la revocación),
no un comando copiable en "Operaciones". Sin socket de Docker para operaciones de PKI.

Estado: ⬜ pendiente · 🚧 en curso · ✅ hecho.

## Fase A — Cerrar brechas NIST (gap analysis previo)

### A1. Revocación distribuida: CRL + OCSP  🚧
- ✅ `crl` habilitado en la intermedia principal (top-level en ca.json + bootstrap.sh).
  step-ca sirve el CRL (DER) en `GET /crl`; se regenera al revocar (`generateOnRevoke`).
- ✅ UI: Inventario → "Lista de revocación (CRL)": estado, vigencia, lista de seriales
  revocados y **descarga** del CRL, por CA emisora (/api/crl, /api/crl-info).
- ✅ CRL también en intermedias adicionales: add/import-intermediate.sh lo generan, y
  las existentes (int-b/int-c) quedaron con CRL (enabled, servido en /crl).
- ⬜ OCSP: evaluar responder (step-ca no trae OCSP nativo; opción CRL-only + doc).
- NIST: 800-15 (repositorios), 800-57 (revocación), 800-53 SC-17.

### A2. Custodia de claves: KMS/HSM + Root offline  🚧
- ✅ UI: panel "Custodia de claves" en Configuración (/api/key-custody): tipo de KMS por
  CA (software/pkcs11/cloud), badge HSM vs software, y aviso NIST si es software.
- ⬜ Soporte PKCS#11 opt-in vía env (documentado en hardening §2) + verificación desde la UI.
- ✅ UI: indicador Root online/offline (NIST sugiere offline). ⬜ guía de ceremonia.

### A3. Gobierno documental: CP/CPS + políticas  ✅ (doc) / 🟡 (policy editor)
- ✅ Plantilla CP/CPS (RFC 3647) en docs/CP-CPS.md, montada y visible/descargable desde
  la UI (/api/cp-cps); check "CP/CPS documentado" en el dashboard de Cumplimiento.
- 🟡 Editor de policy.x509 vía Admin API BLOQUEADO: la policy inline en el ca.json deja
  al provisioner en standalone mode; step ca policy exige policy gestionada en DB.
- ✅ Alternativa lograda: edición de CLAIMS de duración por provisioner (A5).

### A4. Auditoría y trazabilidad  ✅ (núcleo)
- ✅ UI: sección "Auditoría" — línea de tiempo de emisiones (inventario) + revocaciones
  (DB, con método/motivo), seriales correlacionados, ordenada por tiempo (/api/audit).
- ✅ Exportar audit log a CSV (/api/audit.csv). ⬜ firma del export (follow-up).
- ✅ Eventos de provisioners (alta/baja, createdAt/deletedAt) en el feed de auditoría.
- ⬜ Auditoría multi-issuer (revocaciones de int-b/int-c) — follow-up.

### A5. Endurecimiento de emisión  ⬜
- ⬜ UI: edición de claims (duraciones min/max/default) por provisioner vía Admin API.
- ⬜ UI: gestión de plantillas X509 (perfiles de emisión).

## Fase B — Features de PKIs comerciales/OSS (research → implementar en UI)

Catálogo a relevar (EJBCA, Smallstep Certificate Manager, HashiCorp Vault PKI,
Microsoft ADCS, DigiCert, Venafi, OpenXPKI, Dogtag/FreeIPA, Keyfactor):
- ⬜ Relevar features y puntearlas (docs/pki-feature-matrix.md).
- ⬜ Priorizar las implementables sin socket y útiles, e integrarlas a la UI.

(Candidatas típicas: dashboards de expiración, alertas de vencimiento, búsqueda/
filtrado de certs, roles/RBAC, ACME EAB, plantillas/perfiles, SCEP/EST, bulk ops,
notificaciones, reporting/compliance, API keys, multi-tenant, métricas.)

## Bitácora
- (init) Roadmap creado. Arranque por A1 (CRL).
- B-research ✅ docs/pki-feature-matrix.md (relevamiento comerciales/OSS).
- B1 ✅ Inventario: búsqueda/filtrado + chips de estado clickeables.
- A4 ✅ Sección Auditoría (emisiones+revocaciones, /api/audit + CSV).
- A2 ✅ (panel) Custodia de claves en la UI (/api/key-custody, avisos NIST).
- B3 ✅ RBAC: roles viewer/operator/admin (tokens + /api/whoami, gating por endpoint).
- B5 ✅ Revocación masiva de los certs filtrados (/api/revoke-bulk, operator+).
- A5/cfg ✅ Edición de claims de duración por provisioner (/api/provisioner-claims).
- compliance ✅ Dashboard de Cumplimiento NIST en vivo (/api/compliance, sección UI).
- A3 ✅ (doc) CP/CPS RFC 3647 (docs/CP-CPS.md) visible en la UI (/api/cp-cps).
- ops ✅ Smoke/health EJECUTABLE desde la UI (/api/operations/run/smoke, operator+).
- B2 ✅ Alertas de vencimiento por webhook (/api/webhook-test, /api/notify-expiring).
- A4+ ✅ Auditoría con eventos de provisioner (alta/baja) además de emisión/revocación.
