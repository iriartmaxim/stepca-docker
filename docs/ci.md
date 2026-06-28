# CI/CD y calidad

## Pipeline (`.github/workflows/ci.yml`)

| Job | Qué hace |
|-----|----------|
| `lint` | `shellcheck` de los scripts, `yamllint`, y `docker compose config` (base y prod) |
| `secrets-scan` | `gitleaks` sobre todo el historial para impedir reintroducir secretos |
| `e2e` | Levanta el stack real, genera secretos y corre `smoke-test.sh` hasta que las 3 CAs respondan |

## Pin de imagen por digest

Pinear por tag (`STEPCA_IMAGE=smallstep/step-ca:0.28.3`) evita `latest`, pero el
tag puede moverse. Para inmutabilidad total, pineá por **digest**:

```bash
docker pull smallstep/step-ca:0.28.3
docker inspect --format='{{index .RepoDigests 0}}' smallstep/step-ca:0.28.3
# => smallstep/step-ca@sha256:abc123...
```

Y en `.env`:

```dotenv
STEPCA_IMAGE=smallstep/step-ca@sha256:abc123...
```

## Dependabot

`.github/dependabot.yml` abre PRs semanales para actualizar:
- la imagen Docker de step-ca,
- las acciones de GitHub del pipeline.

Cada PR dispara el CI completo (lint + escaneo + E2E), así una actualización no
entra si rompe el arranque.

## Ejecutar el lint localmente

```bash
shellcheck scripts/*.sh local_scripts/*.sh
yamllint compose.yaml compose.prod.yaml pki-ansible.yaml
docker compose config >/dev/null && echo OK
```
