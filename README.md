# stepca-docker

PKI jerárquica con [Smallstep `step-ca`](https://smallstep.com/docs/step-ca/) sobre
Docker Compose, en topología de **alta disponibilidad**: **Root CA → Intermediate CA
(2 réplicas) → Registration Authority (2 réplicas) con ACME**, sobre **PostgreSQL**
compartido y detrás de un **balanceador HAProxy**, con observabilidad y UI incluidas.

```mermaid
flowchart TD
    R["🔐 stepca-root<br/>Root CA"]
    subgraph INT["Intermediate CA (HA)"]
      I1["stepca-int-1"]; I2["stepca-int-2"]
    end
    subgraph RAS["Registration Authority (HA)"]
      A1["stepca-ra-1"]; A2["stepca-ra-2"]
    end
    LB["⚖️ HAProxy<br/>:9001 int · :9100 ra"]
    PG[("🐘 PostgreSQL<br/>stepca_int / stepca_ra")]
    R -- "firma cert intermedio" --> INT
    LB --> INT
    LB --> RAS
    RAS -- "ra_jwk vía LB" --> LB
    INT --- PG
    RAS --- PG
    C["clientes (*.local)"] -- "ACME" --> LB
```

| Servicio | Rol | Puerto host | Notas |
|----------|-----|-------------|-------|
| `postgres` | DB compartida (`stepca_int`/`stepca_ra`) | — | habilita la HA |
| `stepca-root` | Root CA (raíz de confianza) | `9000` | única |
| `stepca-int-1`/`-2` | Intermediate CA (emisora) | `9001` (vía LB) | 2 réplicas, PostgreSQL |
| `stepca-ra-1`/`-2` | Registration Authority (ACME) | `9100` (vía LB) | 2 réplicas, PostgreSQL |
| `haproxy` | Balanceador L4 | `9001`,`9100`,`8404` | alias `stepca-intermediate`, `stepca-ra-one.local` |
| `prometheus`/`grafana` | Observabilidad | `9090`/`3000` | |
| `stepca-ui` | Dashboard de administración | `8088` | sólo lectura |

---

## Requisitos

- Docker Engine 20.10+ y Docker Compose v2 (`docker compose`)
- `bash`, `openssl`, `step` CLI y `jq` en el host (para los scripts auxiliares)
- En Windows: usar **WSL2** o Git Bash para los scripts `.sh`

## Quickstart

```bash
# 1. Configuración (opcional: ajustá nombres/puertos)
cp .env.example .env

# 2. Levantar TODO el stack sin pasos manuales
make up        # corre scripts/bootstrap.sh: secretos + claves + configs + arranque

# 3. Verificar salud
make status
make test      # smoke test de las 3 CAs
```

`make up` ejecuta [scripts/bootstrap.sh](scripts/bootstrap.sh), que de forma
idempotente: genera contraseñas fuertes, crea el par de claves del provisioner
`ra_jwk`, escribe las configs de la Intermediate y la RA (con el fingerprint de la
Root resuelto automáticamente) y levanta las 3 CAs en orden. No requiere Ansible
ni intervención manual.

> ⚠️ La primera vez, la Root CA genera y firma el certificado intermedio; el
> bootstrap espera a que cada CA esté `healthy` antes de seguir.

## Despliegue automatizado (Ansible)

Alternativa que destruye y recrea todo el entorno de forma idempotente:

```bash
ansible-playbook pki-ansible.yaml          # usa el dir del playbook como raíz
ansible-playbook pki-ansible.yaml -e docker_compose_dir=/ruta/al/repo
```

## Comandos útiles (Makefile)

| Comando | Acción |
|---------|--------|
| `make secrets` | Genera contraseñas fuertes en `secrets/` |
| `make up` / `make down` | Levanta / detiene el stack |
| `make reset` | **Destruye** estado y vuelve a levantar de cero |
| `make status` | Estado y salud de los servicios |
| `make logs` | Sigue los logs de los 3 servicios |
| `make test` | Smoke test end-to-end (salud de las 3 CAs) |
| `make config` | Valida `docker compose config` |

## Confiar en la Root CA (clientes)

```bash
# Exportar la raíz
docker exec stepca-root cat /home/step/certs/root_ca.crt > root_ca.crt

# Linux (Debian/Ubuntu)
sudo cp root_ca.crt /usr/local/share/ca-certificates/stepca-root.crt && sudo update-ca-certificates
# macOS
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain root_ca.crt
# Windows (PowerShell admin)
Import-Certificate -FilePath root_ca.crt -CertStoreLocation Cert:\LocalMachine\Root
```

## Emitir un certificado vía ACME

La RA expone un provisioner ACME en `https://stepca-ra-one.local:9100/acme/acme/directory`.
Ver [docs/issuing-certs.md](docs/issuing-certs.md) para ejemplos con `step`, `certbot`,
nginx, Traefik y cert-manager.

## Estructura del repositorio

```
.
├── compose.yaml            # orquestación de los 3 servicios
├── .env.example            # variables de configuración (copiar a .env)
├── pki-ansible.yaml        # despliegue automatizado idempotente
├── Makefile                # atajos de operación
├── scripts/
│   ├── bootstrap.sh        # orquesta el despliegue completo (lo usa `make up`)
│   ├── gen-secrets.sh      # genera contraseñas fuertes
│   ├── init-root.sh        # crea y firma el cert intermedio
│   └── init-intermediate.sh# aprovisiona la intermedia (idempotente)
├── local_scripts/
│   └── key_ra.sh           # extrae el JWK ra_jwk → ra.key.pem para la RA
├── secrets/                # contraseñas (gitignored; solo *.example versionado)
├── persistent/             # estado de las CAs (gitignored)
└── docs/                   # documentación extendida
```

## Seguridad

Leé **[SECURITY.md](SECURITY.md)**. Resumen:

- `secrets/` y `persistent/` están en `.gitignore` — **nunca** los versiones.
- Generá contraseñas con `scripts/gen-secrets.sh`, no uses valores por defecto.
- Las versiones iniciales del repo filtraron material sensible: ver el runbook de
  purga de historial y regeneración de PKI en `SECURITY.md`.

## Documentación

| Doc | Contenido |
|-----|-----------|
| [docs/architecture.md](docs/architecture.md) | Arquitectura, niveles y flujo de aprovisionamiento |
| [docs/issuing-certs.md](docs/issuing-certs.md) | Emitir certs (step, certbot, nginx, Traefik, cert-manager) |
| [docs/acme-challenges.md](docs/acme-challenges.md) | Challenges ACME: http-01, dns-01, tls-alpn-01, device-attest-01 |
| [docs/operations.md](docs/operations.md) | Backup/restore, renovación de la intermedia, logging |
| [docs/hardening.md](docs/hardening.md) | SOPS, KMS/HSM, Root offline, políticas, CRL/OCSP |
| [docs/secure-access.md](docs/secure-access.md) | Interacción segura con la PKI (API autenticada, pinning, cliente endurecido) |
| [docs/observability.md](docs/observability.md) | Prometheus + Grafana |
| [docs/scaling.md](docs/scaling.md) | Multi-RA y HA con DB externa |
| [docs/ci.md](docs/ci.md) | Pipeline CI, pin por digest, Dependabot |
| [examples/](examples/) | Manifiestos de clientes (cert-manager, Traefik, nginx) |
| [charts/stepca/](charts/stepca/) | Helm chart para Kubernetes |

## Despliegue

Todo está en un único `compose.yaml` (HA, performance y observabilidad), orquestado
por `make up`. Overlays opt-in para casos puntuales:

```bash
make up                                                   # stack HA completo
make stats                                                # estado + URL de HAProxy
make backup-pg                                            # dump de las DBs PostgreSQL
docker compose -f compose.yaml -f compose.ui-full.yaml up -d --build stepca-ui  # UI con control (privilegiado)
docker compose -f compose.yaml -f compose.acme-demo.yaml up -d                  # CoreDNS para demo dns-01
```

Endpoints: Intermediate `https://localhost:9001` y RA `https://localhost:9100` (vía
HAProxy), Root `https://localhost:9000`, HAProxy stats `http://localhost:8404`,
Grafana `:3000`, Prometheus `:9090`, UI `:8088`.

## Alta disponibilidad

- **PostgreSQL primario + standby** (replicación en streaming): las CAs usan un DSN
  multi-host (`target_session_attrs=read-write`) y reconectan solas al nuevo primario
  tras un failover. `make pg-failover` promueve el standby; `make pg-status` muestra
  la replicación.
- **2 réplicas** de Intermediate y **2 de RA** detrás de **HAProxy** (L4, TCP
  passthrough; los alias `stepca-intermediate` y `stepca-ra-one.local` apuntan al LB).
- Failover verificado end-to-end: caída una réplica de CA el LB sigue sirviendo; y
  tras promover el standby de Postgres, las CAs siguen **emitiendo** (escritura en DB).
- Límites de CPU/memoria por servicio (performance acotada y predecible).

## Acceso seguro

Para operar la PKI sin exponer el socket de Docker, usá el **cliente operador
endurecido** (`make step`): un `step` CLI efímero que ancla la confianza al
fingerprint de la Root y opera vía la **API autenticada** de step-ca. Detalle del
modelo en [docs/secure-access.md](docs/secure-access.md).

## UI de administración

Dashboard web en `http://localhost:8088` (incluido en `make up`): estado en vivo,
certificados de las CAs, **inventario de certificados emitidos** y provisioners ACME.
Por defecto **sólo lectura** (no monta el socket de Docker). El modo completo (control
de servicios y emisión) se habilita con el overlay `compose.ui-full.yaml`, que monta
`/var/run/docker.sock` — superficie privilegiada, sólo en entornos de confianza.

## Roadmap

Plan de mejora por fases (seguridad → arranque → docs → operación → hardening →
CI → escala) en **[ROADMAP.md](ROADMAP.md)**.

## Licencia

Ver [LICENSE](LICENSE).
