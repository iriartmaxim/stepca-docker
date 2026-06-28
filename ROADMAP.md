# Roadmap — stepca-docker

Plan de mejora por fases, ordenado por impacto. Cada fase es entregable de forma
independiente. Estado: ✅ hecho · 🚧 en progreso · ⬜ pendiente.

---

## 🔴 Fase 0 — Contención de seguridad

| # | Acción | Estado |
|---|--------|--------|
| 0.1 | `.gitignore` para `secrets/`, `persistent/`, `*_key`, `*password*` | ✅ |
| 0.2 | Untrack de secretos del índice (`git rm --cached`) | ✅ |
| 0.3 | Plantillas `secrets/*.example` + `scripts/gen-secrets.sh` (openssl rand) | ✅ |
| 0.4 | `SECURITY.md` con runbook de purga de historial + regeneración de PKI | ✅ |
| 0.5 | Purgar el historial git (`git filter-repo`) — **acción del responsable** | ⬜ |
| 0.6 | Regenerar toda la PKI con secretos nuevos (`make reset`) | ⬜ |

## 🟠 Fase 1 — Arranque limpio y reproducible

| # | Acción | Estado |
|---|--------|--------|
| 1.1 | Eliminar volumen `init-script` roto (apuntaba a archivo inexistente) | ✅ |
| 1.2 | RA sin modo degradado (`step-ca ... \|\| true; tail -f`) | ✅ |
| 1.3 | `init-intermediate.sh` autosuficiente e idempotente | ✅ |
| 1.4 | Resolver conflicto de doble montaje en `/home/step/certs` | ✅ |
| 1.5 | Unificar `badgerv2` / `badgerV2` | ✅ |
| 1.6 | `.env.example` + parametrización de imagen, puertos y nombres | ✅ |
| 1.7 | Rutas Linux hardcodeadas → derivadas del repo (`key_ra.sh`, Ansible) | ✅ |
| 1.8 | Pin de versión de imagen (`STEPCA_IMAGE`) en vez de `latest` | ✅ |
| 1.9 | Validar arranque E2E real con `make reset` en máquina limpia | ⬜ |

## 🟡 Fase 2 — Documentación y UX

| # | Acción | Estado |
|---|--------|--------|
| 2.1 | `README.md` completo con diagrama | ✅ |
| 2.2 | `Makefile` (up/down/reset/status/logs/test) | ✅ |
| 2.3 | `docs/architecture.md` y `docs/issuing-certs.md` | ✅ |
| 2.4 | `scripts/smoke-test.sh` | ✅ |
| 2.5 | Guía de confianza de la Root CA (Win/Linux/macOS) | ✅ |

## 🟢 Fase 3 — Operación y robustez

| # | Acción | Estado |
|---|--------|--------|
| 3.1 | Override `compose.prod.yaml` con límites de recursos y `read_only` | ✅ |
| 3.2 | Healthchecks correctos en los 3 servicios | ✅ |
| 3.3 | Script/target de backup y restore de la DB badger (`scripts/backup.sh`, `restore.sh`) | ✅ |
| 3.4 | Logging estructurado + rotación (`docs/operations.md`, prod override) | ✅ |
| 3.5 | Renovación automática de la intermedia (`scripts/renew-intermediate.sh`) | ✅ |

## 🔵 Fase 4 — Hardening avanzado

| # | Acción | Estado |
|---|--------|--------|
| 4.1 | Gestor de secretos externo (SOPS+age: `.sops.yaml`, `docs/hardening.md`) | ✅ |
| 4.2 | Clave raíz en KMS/HSM vía PKCS#11 (ejemplos en `docs/hardening.md`) | ✅ |
| 4.3 | Root CA offline (perfil prod + runbook en `docs/hardening.md`) | ✅ |
| 4.4 | Endurecer políticas X509/ACME (allowlists, duraciones) | ✅ |
| 4.5 | Revocación CRL/OCSP (config + comandos en `docs/hardening.md`) | ✅ |

## 🟣 Fase 5 — CI/CD y calidad

| # | Acción | Estado |
|---|--------|--------|
| 5.1 | CI: lint (yamllint, shellcheck) + `compose config` | ✅ |
| 5.2 | CI: escaneo de secretos (gitleaks) | ✅ |
| 5.3 | CI: test de integración E2E (levantar stack + smoke test) | ✅ |
| 5.4 | Pin de imagen por digest (`docs/ci.md`) + Dependabot (`.github/dependabot.yml`) | ✅ |

## 🌟 Fase 6 — Escalabilidad

| # | Acción | Estado |
|---|--------|--------|
| 6.1 | Templating multi-RA / multi-tenant (`docs/scaling.md`, Helm `values.ra[]`) | ✅ |
| 6.2 | DB externa (PostgreSQL) para HA de la intermedia (`compose.ha.yaml`) | ✅ |
| 6.3 | Métricas Prometheus + dashboard Grafana (`observability/`) | ✅ |
| 6.4 | Ejemplos cert-manager / nginx / Traefik (`examples/`) | ✅ |
| 6.5 | Helm chart para Kubernetes (`charts/stepca/`) | ✅ |

---

> **Nota sobre validación:** los artefactos de las Fases 3-6 (backup, renovación,
> HA, observabilidad, Helm) están escritos y validados sintácticamente
> (`docker compose config`). La validación funcional end-to-end (correr un backup
> real, desplegar el chart en un cluster, etc.) queda pendiente de un entorno con
> la infraestructura correspondiente.
