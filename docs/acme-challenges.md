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

## 2. dns-01  ✅ demo incluido

La RA verifica un registro TXT `_acme-challenge.<dominio>`. Sirve para **wildcards**
y cuando no podés exponer puertos. Requiere un servidor DNS que la RA consulte.

El demo incluye esa infraestructura: `compose.acme-demo.yaml` añade un **CoreDNS**
autoritativo (red `acme-demo`, IP `172.31.0.53`) y hace que la RA lo use como
resolver; el cliente lego publica el TXT con el hook `examples/acme/lego-exec.sh`.

```bash
# Levanta CoreDNS, reconfigura la RA y emite el cert con dns-01
examples/acme/demo-dns01.sh dnsdemo.test
# Revertir la RA a su DNS normal al terminar:
docker compose up -d --force-recreate stepca-ra-one.local
```

> ⚠️ **Dos detalles aprendidos en este repo**:
> 1. Usá un TLD **`.test`**, no `.local`: `.local` está reservado para mDNS.
> 2. Un solo TXT por nombre: registros TXT duplicados hacen fallar la validación.

`acme.sh` / cert-manager también sirven (cambiando el directory a `/acme/acme-dns/`),
ver [../examples/cert-manager-clusterissuer.yaml](../examples/cert-manager-clusterissuer.yaml).

## 3. tls-alpn-01  ✅ demo incluido

La RA se conecta al **puerto 443** y negocia ALPN `acme-tls/1`. Lo implementan los
clientes/servidores con ACME embebido (lego, Caddy, Traefik); el CLI `step` no.

```bash
# Demo con lego (levanta el servidor TLS-ALPN y emite el cert)
examples/acme/demo-tlsalpn01.sh tlsdemo.local
```

Caddy:

```caddyfile
demo.local {
  tls { ca https://stepca-ra-one.local:9100/acme/acme-tls/directory
        ca_root root_ca.crt }
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

El scaffold con TPM por software (swtpm) y el flujo completo están en
[../examples/acme/demo-deviceattest01.sh](../examples/acme/demo-deviceattest01.sh):

```bash
examples/acme/demo-deviceattest01.sh   # imprime el flujo y los requisitos
```

> A diferencia de los otros 3, depende de **hardware de atestación** (o un emulador
> swtpm) y de registrar la cadena del EK del TPM en `attestationRoots` del
> provisioner. El provisioner ya está activo; falta la raíz de confianza del EK,
> específica de cada TPM/fabricante.

---

## Resumen de verificación en este repo

| Challenge | Provisioner | Demo E2E (probado) |
|-----------|-------------|--------------------|
| http-01 | `acme-http` | ✅ cert emitido (`step --standalone`) |
| dns-01 | `acme-dns` | ✅ validado con CoreDNS + lego (usar `.test`) |
| tls-alpn-01 | `acme-tls` | ✅ cert emitido (lego `--tls`) |
| device-attest-01 | `acme-device` | ⚙️ scaffold (requiere TPM/atestación) |

Infraestructura de demo: `compose.acme-demo.yaml` (CoreDNS) + `examples/acme/`
(scripts y hooks). Cliente ACME usado: [lego](https://go-acme.github.io/lego/)
y el CLI `step`.
