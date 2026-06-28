# Acceso seguro a la PKI

Cómo interactuar con la PKI de forma segura, según el modelo de
[step-ca](https://smallstep.com/docs/step-ca/).

## Principio: nunca el socket de Docker para operar la PKI

Montar `/var/run/docker.sock` en una herramienta equivale a **root sobre el host**
(puede crear/controlar cualquier contenedor). Es una superficie de RCE y **no** es
la forma de administrar la PKI. Por eso la UI de este repo es **sólo lectura por
defecto** y el modo con socket es opt-in y desaconsejado salvo en local de confianza.

La forma correcta es la **API autenticada de step-ca**, sobre TLS, con la **Root
anclada por fingerprint**.

## Los canales autenticados de step-ca

| Canal | Para qué | Autenticación |
|-------|----------|---------------|
| **Provisioners** | emitir/renovar certificados | JWK (contraseña), OIDC (identidad), ACME (control de dominio/dispositivo), X5C, etc. |
| **Admin API** (`enableAdmin`) | gestionar provisioners y admins en caliente | admin (super-admin) con JWK + JWT |
| **mTLS** | servicio↔CA y cliente↔servicio | certificado de cliente |

Toda petición queda **auditada** en los logs de step-ca (`make logs`).

## Cliente operador endurecido

`scripts/step-shell.sh` (`make step`) levanta un cliente `step` **efímero** que:

- establece confianza con `step ca bootstrap` **pinneando la Root por fingerprint**
  (no "confía a ciegas"),
- **no** monta el socket de Docker ni claves de CA,
- se borra al salir (no deja credenciales en disco).

```bash
make step                                  # shell interactivo ya bootstrapeado
scripts/step-shell.sh ca health            # comando puntual
scripts/step-shell.sh ca provisioner list  # consulta autenticada vía API
```

Desde ese shell, las operaciones se autentican con el provisioner correspondiente:

```bash
# Emitir con un provisioner JWK (pide contraseña del provisioner)
step ca certificate app.local app.crt app.key --provisioner <jwk-name>

# Emitir vía ACME (control de dominio; sin contraseña de provisioner)
step ca certificate app.local app.crt app.key \
  --provisioner acme-http --ca-url https://stepca-ra-one.local:9100 --standalone
```

## Interacción por web (UI)

La UI (`http://localhost:8088`) aplica el mismo principio: **no monta el socket de
Docker**. Para emitir certificados desde la web usa la API autenticada de step-ca
con un provisioner JWK dedicado (`web`), acotado por política (`*.local`):

- el backend sólo tiene la **contraseña del provisioner** (secreto montado), nunca
  el socket ni la clave de CA;
- la emisión exige un **token de operador** (`UI_TOKEN`) en el header `X-Auth-Token`;
- el nombre se valida (regex `*.local`) y la llamada a `step` es por argv (sin shell).

Sin `UI_TOKEN`, la UI queda **sólo lectura**. Es la versión web del cliente `make step`.

## Buenas prácticas (defensa en profundidad)

- **Mínimo privilegio**: acotá cada provisioner con `policy` (allowlist de nombres) y
  duraciones cortas; separá el provisioner de **emisión** del de **administración**.
- **Secretos fuera de la imagen**: las contraseñas de provisioner se pasan en runtime
  (prompt o secret), nunca embebidas en imágenes/env. En producción, gestor de
  secretos (Vault/SOPS) — ver [hardening.md](hardening.md).
- **Root offline y KMS/HSM**: protegé la clave raíz (ver [hardening.md](hardening.md)).
- **Pinning**: distribuí el `root_ca.crt` y su fingerprint por un canal confiable;
  los clientes hacen `step ca bootstrap --fingerprint <fp>`.
- **Revocación y rotación**: CRL/OCSP y rotación de provisioners documentadas en
  [hardening.md](hardening.md).
- **Red**: exponé sólo lo necesario. La Root puede quedar sin publicar (firma la
  intermedia y se apaga); la emisión va por la RA/Intermediate detrás del balanceador.
- **Auditoría**: centralizá los logs de step-ca (formato `json`, ver
  [observability.md](observability.md)).

## Qué evitar

- ❌ Montar el socket de Docker en servicios web/UI para operar la PKI.
- ❌ Embeber contraseñas de provisioner o claves de CA en imágenes o variables.
- ❌ Confiar en la CA sin verificar el fingerprint de la Root.
- ❌ Provisioners sin política (que emitan cualquier nombre) o de larga duración sin necesidad.
