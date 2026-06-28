# Matriz de features — PKIs comerciales/OSS vs. este proyecto

Relevamiento de funcionalidades de productos de PKI/CLM y su estado en este proyecto.
Objetivo: incorporar las útiles **gestionables desde la UI** (sin socket de Docker).

Productos relevados: **EJBCA / Keyfactor Command** (CA + CLM, todos los protocolos),
**Venafi / CyberArk** (CLM, motor de políticas granular), **Smallstep Certificate
Manager** (step-ca + UI, ACME/EAB/SCEP, device identity), **HashiCorp Vault PKI**
(secrets engine, ACME), **Microsoft ADCS**, **OpenXPKI**, **Dogtag/FreeIPA**.

Leyenda: ✅ tiene · 🟡 parcial · ⬜ falta · ★ priorizado para implementar en la UI.

| # | Feature | Comerciales/OSS | Este proyecto | Acción |
|---|---------|-----------------|---------------|--------|
| 1 | Inventario / lifecycle de certs | EJBCA, Keyfactor, Venafi | ✅ Inventario + emisión/revocación/inspección | — |
| 2 | **Búsqueda y filtrado** de certs | todos | ⬜ | ★ B1 (este tick) |
| 3 | **Monitoreo de vencimientos** (buckets, % por estado) | todos | 🟡 (pills) | ★ B1 |
| 4 | **Alertas/notificaciones** de expiración (webhook/email) | Keyfactor, Venafi | ⬜ | ★ B2 |
| 5 | Reporting/compliance export | todos | ✅ CSV | 🟡 ampliar |
| 6 | **RBAC / roles** | EJBCA, Keyfactor, Venafi | ✅ viewer/operator/admin | — |
| 7 | Motor de políticas (allow/deny, name constraints) | Venafi, EJBCA | 🟡 policy.x509 | ★ A3 (editor en UI) |
| 8 | ACME | step-ca, Vault, EJBCA | ✅ 4 challenges | — |
| 9 | **ACME EAB** (External Account Binding) | Smallstep, EJBCA | ⬜ | ★ B4 |
| 10 | SCEP / EST / CMP | EJBCA (todos), Smallstep (SCEP/EST) | ⬜ (device via ACME) | ⬜ evaluar |
| 11 | **Plantillas/perfiles** de emisión gestionables | EJBCA (cert profiles), ADCS | 🟡 archivos .tpl | ★ A5 (ver/seleccionar en UI) |
| 12 | **Operaciones masivas** (bulk revoke/export) | Keyfactor, Venafi | ✅ bulk revoke + CSV | — |
| 13 | **Audit log / trazabilidad** | todos | ✅ vista Auditoría + CSV | — |
| 14 | Gestión de claves / HSM | EJBCA, todos | ✅ panel de custodia | 🟡 PKCS#11 opt-in |
| 15 | Multi-CA / multi-issuer | EJBCA, Keyfactor | ✅ multi-intermediate | — |
| 16 | Métricas / observabilidad | Keyfactor, Venafi | ✅ Grafana/Prometheus | — |
| 17 | Portal self-service de enrolamiento | todos | ✅ UI de emisión | — |
| 18 | API REST | todos | ✅ FastAPI | — |

## Backlog priorizado (gestionable desde la UI)
- **B1** ★ Búsqueda/filtrado + resumen de vencimientos en el inventario. (en curso)
- **B2** Alertas de expiración (resumen + webhook opcional).
- **B3** RBAC: roles (viewer/operator/admin) sobre el token.
- **B4** ACME EAB: alta/baja de credenciales EAB por provisioner.
- **B5** Operaciones masivas (bulk revoke por filtro).
- (+ A2 custodia de claves, A3 editor de políticas, A4 audit log, A5 plantillas).

Fuentes: comparativas EJBCA/Keyfactor/Venafi y step-ca/Vault (Keyfactor docs,
Smallstep, Axelspire 2026).
