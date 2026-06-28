# Certificate Policy / Certification Practice Statement (CP/CPS)

Estructura RFC 3647. Tallado a este PKI (step-ca en HA). Los campos `[ORG: …]` deben
completarse con datos de la organización antes de un uso productivo.

- **Versión:** 0.1 (borrador) · **OID de la política:** `[ORG: 1.3.6.1.4.1.<PEN>.1.1]`
- **Estado:** laboratorio / referencia · cerrar brechas de `docs/hardening.md` para producción.

## 1. Introducción
- **1.1 Resumen.** PKI privada de dos niveles: Root CA offline-capaz → Intermediate CA(s)
  en alta disponibilidad (2 réplicas tras HAProxy, PostgreSQL primario/standby) → entidades
  finales. Autoridad de Registro (RA) dedicada para enrolamiento ACME.
- **1.2 Identificación.** Este documento es el CP y el CPS combinados. OID: `[ORG]`.
- **1.3 Participantes.** CA (Root, Intermediates), RA (ACME), suscriptores (entidades
  finales), partes confiantes (relying parties), repositorio (CRL en `GET /crl`, ancla
  vía la UI). Roles operativos: **admin / operator / viewer** (RBAC, ver §5.2).
- **1.4 Uso de certificados.** TLS de servidor/cliente para servicios internos `*.local`.
  Prohibido: uso fuera de la política x509 del provisioner.
- **1.5 Administración de la política.** `[ORG: contacto, proceso de cambios y aprobación]`.

## 2. Publicación y responsabilidades del repositorio
- **2.1 Repositorio.** CRL DER en `GET /crl` de cada CA emisora (regenerado al revocar,
  `cacheDuration` 12h). Ancla de confianza descargable desde la UI (`/api/root.crt`).
- **2.2 Publicación.** El ancla raíz se distribuye a los almacenes de confianza por
  `[ORG: MDM/GPO/Ansible]`. CRL accesible para las partes confiantes.
- **2.3 Frecuencia.** CRL: al revocar + ventana de cache 12h. `[ORG: SLA de publicación]`.

## 3. Identificación y autenticación
- **3.1 Nombres.** CN/SAN DNS bajo `*.local` (política x509 del provisioner `web`,
  `allowWildcardNames=false`). `[ORG: espacio de nombres productivo]`.
- **3.2 Validación inicial.** Enrolamiento autenticado: provisioner JWK `web` (clave +
  contraseña, sin socket) para emisión asistida por la UI; ACME (http-01/dns-01/tls-alpn-01/
  device-attest-01) para automatización. `[ORG: EAB para ACME en producción]`.
- **3.3 Re-emisión / renovación.** Renovación mTLS del propio certificado; revocación pasiva
  bloquea la renovación de certificados revocados.

## 4. Requisitos operativos del ciclo de vida
- **4.1 Solicitud.** Vía UI (rol operator+) o cliente ACME.
- **4.2-4.4 Emisión / aceptación.** Emisión por la Intermediate CA; el suscriptor recibe el
  cert + cadena. Inventario y auditoría en la UI.
- **4.5 Pares de claves y uso.** EC P-256 (hojas) / RSA-4096 (sub-CA). KeyUsage/EKU por
  plantilla (`web-leaf.tpl`: serverAuth+clientAuth).
- **4.6-4.8 Renovación / re-key / modificación.** Certificados de vida corta
  (`maxTLSCertDuration` 24h) → preferir re-emisión frecuente sobre renovación prolongada.
- **4.9 Revocación y suspensión.** Revocación pasiva + CRL. Desde la UI (rol operator+),
  individual o **masiva**. Motivo/método quedan en la auditoría. Sin suspensión.
- **4.10 Servicios de estado.** CRL. OCSP: no provisto por step-ca (CRL-only). `[ORG]`.

## 5. Controles de instalación, gestión y operación
- **5.1 Físicos.** `[ORG: datacenter, acceso físico]`.
- **5.2 Procedimentales (separación de funciones).** RBAC: **admin** (provisioners,
  settings, intermedias), **operator** (emitir/revocar), **viewer** (lectura). NIST 800-53 AC-5/6.
- **5.3 Personal.** `[ORG: roles de confianza, screening]`.
- **5.4 Auditoría de eventos.** Feed de auditoría (emisión + revocación) en la UI y export CSV.
  `[ORG: retención, protección del log, NIST 800-53 AU]`.
- **5.5-5.8 Archivo / cambio de clave / recuperación / cese.** Backups de la DB
  (`make backup` / `restore`). `[ORG: archivado cifrado y probado, plan de continuidad]`.

## 6. Controles técnicos de seguridad
- **6.1 Generación y protección de claves.** **Brecha actual:** claves de CA en archivo
  cifrado en disco. **Objetivo NIST 800-57:** HSM/PKCS#11 (ver `hardening §2`).
- **6.2 Protección de la clave privada.** Contraseñas vía secret files (objetivo: SOPS/Vault,
  `hardening §1`). Root **offline** recomendado (`hardening §3`).
- **6.3-6.7 Periodos / datos de activación / seguridad de cómputo y red.** Cripto-períodos
  cortos (24h). TLS interno, contenedores con límites de recursos.

## 7. Perfiles de certificado, CRL y OCSP
- **7.1 Certificado.** X.509 v3; plantillas por provisioner; SAN DNS; EKU server/clientAuth.
- **7.2 CRL.** v2, firmada por la Intermediate, `nextUpdate` 12h.
- **7.3 OCSP.** No aplicable (CRL-only).

## 8. Auditoría de cumplimiento
- Tablero de **Cumplimiento (NIST)** en la UI (`/api/compliance`): CRL, custodia de claves,
  Root offline, RBAC, vigencia corta, auditoría. `[ORG: auditoría externa, periodicidad]`.

## 9. Asuntos legales y comerciales
- `[ORG: responsabilidades, garantías, privacidad, propiedad intelectual, ley aplicable]`.

---
_Plantilla generada para este proyecto. Revisar con asesoría legal/seguridad antes de
producción. Brechas técnicas y su remediación: `docs/hardening.md`._
