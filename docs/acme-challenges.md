# Challenges ACME

La RA expone **un provisioner ACME por cada tipo de challenge**, así podés elegir
el método de validación según el caso de uso. Todos aplican la política `*.local`.

| Provisioner | Challenge | Directory URL | Valida demostrando… |
|-------------|-----------|---------------|----------------------|
| `acme-http` | `http-01` | `/acme/acme-http/directory` | control de `http://<dominio>/.well-known/acme-challenge/<token>` (puerto 80) |
| `acme-dns` | `dns-01` | `/acme/acme-dns/directory` | control del DNS vía registro TXT `_acme-challenge.<dominio>` |
| `acme-tls` | `tls-alpn-01` | `/acme/acme-tls/directory` | control del puerto 443 con ALPN `acme-tls/1` |
| `acme-device` | `device-attest-01` | `/acme/acme-device/directory` | posesión de una clave de dispositivo atestiguada (TPM/Apple/Step) |

URL base: `https://stepca-ra-one.local:9100`. Verificá un directorio:

```bash
curl -sk https://localhost:9100/acme/acme-http/directory | jq
```

Configuración (generada por `scripts/bootstrap.sh` en el `ca.json` de la RA):

```json
{ "type": "ACME", "name": "acme-http",   "challenges": ["http-01"] },
{ "type": "ACME", "name": "acme-dns",    "challenges": ["dns-01"] },
{ "type": "ACME", "name": "acme-tls",    "challenges": ["tls-alpn-01"] },
{ "type": "ACME", "name": "acme-device", "challenges": ["device-attest-01"],
  "attestationFormats": ["step","tpm","apple"] }
```

---

## 1. http-01  ✅ demo incluido

El cliente abre un servidor en el **puerto 80** y la RA lo consulta. Es el más
simple si el dominio resuelve a la máquina que pide el cert.

```bash
# Demo automatizado (levanta un cliente en la red de Docker y emite el cert)
examples/acme/demo-http01.sh demo.local
```

Equivalente manual con `step`:

```bash
step ca certificate demo.local demo.crt demo.key \
  --provisioner acme-http \
  --ca-url https://stepca-ra-one.local:9100 \
  --root root_ca.crt --standalone
```

Con `certbot`:

```bash
certbot certonly --standalone \
  --server https://stepca-ra-one.local:9100/acme/acme-http/directory \
  -d demo.local
```

## 2. dns-01

La RA verifica un registro TXT `_acme-challenge.<dominio>`. Sirve para **wildcards**
(`*.local`) y cuando no podés exponer el puerto 80. Requiere un proveedor DNS o
un solver que cree el TXT.

`acme.sh` con un proveedor DNS:

```bash
export STEP_CA_URL=https://stepca-ra-one.local:9100/acme/acme-dns/directory
acme.sh --issue --dns dns_cf -d demo.local -d '*.demo.local' \
  --server "$STEP_CA_URL" --ca-bundle root_ca.crt
```

cert-manager (Kubernetes) con solver dns01 — ver
[../examples/cert-manager-clusterissuer.yaml](../examples/cert-manager-clusterissuer.yaml),
cambiando `server` a `/acme/acme-dns/directory` y el `solver` a `dns01`.

> El CLI `step --standalone` solo implementa http-01; para dns-01 usá acme.sh,
> certbot con plugin DNS, Caddy o cert-manager.

## 3. tls-alpn-01

La RA se conecta al **puerto 443** y negocia ALPN `acme-tls/1`. Lo implementan los
servidores/proxies con ACME embebido, no el CLI `step`.

Caddy (automático):

```caddyfile
demo.local {
  tls {
    ca https://stepca-ra-one.local:9100/acme/acme-tls/directory
    ca_root root_ca.crt
  }
  respond "ok"
}
```

Traefik: ver [../examples/traefik-dynamic.yml](../examples/traefik-dynamic.yml),
apuntando `caServer` a `/acme/acme-tls/directory` y usando `tlsChallenge: {}`.

## 4. device-attest-01

Emite certificados a **dispositivos** que prueban su identidad con una clave
atestiguada por hardware. Formatos habilitados: `step` (agente), `tpm` (TPM 2.0)
y `apple` (Secure Enclave / MDM). El SAN es un `permanentIdentifier` (p. ej. el
serial del dispositivo), no un DNS.

```bash
# Ejemplo con clave en TPM via step + smallstep agent (requiere hardware/atestación)
step ca certificate "device-serial-123" dev.crt dev.key \
  --provisioner acme-device \
  --ca-url https://stepca-ra-one.local:9100 \
  --kms tpmkms: --attestation-uri tpmkms:name=device-key \
  --root root_ca.crt
```

> No se incluye demo automatizado: requiere un TPM/Secure Enclave o un emulador
> (swtpm) y, según el formato, una **attestation CA** registrada en el provisioner.
> Ver la doc de Smallstep sobre *device attestation* para producción.

---

## Resumen de verificación en este repo

| Challenge | Provisioner activo | Demo E2E |
|-----------|--------------------|----------|
| http-01 | ✅ | ✅ cert emitido para `demo.local` |
| dns-01 | ✅ | requiere proveedor DNS (documentado) |
| tls-alpn-01 | ✅ | requiere servidor ALPN (Caddy/Traefik) |
| device-attest-01 | ✅ | requiere hardware de atestación |
