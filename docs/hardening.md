# Hardening avanzado

Guía para llevar el stack de laboratorio a un perfil apto para producción.

---

## 1. Gestión de secretos externa (SOPS + age)

En vez de contraseñas en texto plano bajo `secrets/`, cifralas con
[SOPS](https://github.com/getsops/sops) + [age](https://github.com/FiloSottile/age)
y versioná **solo la versión cifrada**.

```bash
# Generar clave age
age-keygen -o ~/.config/sops/age/keys.txt   # imprime la public key age1...

# Cifrar (ver .sops.yaml para la regla)
sops --encrypt secrets/root_ca_password.txt > secrets/root_ca_password.enc.yaml

# Descifrar en el arranque
sops --decrypt secrets/root_ca_password.enc.yaml > secrets/root_ca_password.txt
```

Ver [`.sops.yaml`](../.sops.yaml). Alternativas equivalentes: **HashiCorp Vault**
(con `vault agent` inyectando los secretos) o **Docker secrets externos** en Swarm.

## 2. Clave raíz en KMS/HSM (PKCS#11)

`step-ca` soporta KMS para que la **clave privada nunca esté en disco plano**.
Ejemplo de bloque `kms` en `ca.json` (PKCS#11 / SoftHSM, YubiHSM, AWS KMS, GCP KMS):

```json
{
  "kms": {
    "type": "pkcs11",
    "uri": "pkcs11:module-path=/usr/lib/softhsm/libsofthsm2.so;token=stepca?pin-value=1234"
  },
  "root": "/home/step/certs/root_ca.crt",
  "crt":  "/home/step/certs/intermediate_ca.crt",
  "key":  "pkcs11:id=2000;object=intermediate-key"
}
```

AWS KMS:

```json
{ "kms": { "type": "awskms", "region": "us-east-1" },
  "key": "awskms:key-id=<KEY_ID>" }
```

## 3. Root CA offline

La Root solo debe estar online para **firmar la intermedia**; luego apagala.

```bash
# Levantar todo, esperar a que la intermedia tenga su cert
make up && make test
# Apagar la Root (la intermedia y la RA siguen operando)
docker compose stop stepca-root
```

`compose.prod.yaml` ya **no publica** el puerto de la Root al host. Para un perfil
estricto, mové la Root a un host aislado y traé solo `root_ca.crt` +
`intermediate_ca.crt`/key firmados.

## 4. Endurecer políticas X509 y ACME

En el `ca.json` de la intermedia, restringí qué se puede emitir:

```json
"policy": {
  "x509": {
    "allow": { "dns": ["*.local", "*.corp.example.com"] },
    "deny":  { "dns": ["*.internal"] },
    "allowWildcardNames": false
  }
}
```

Para el provisioner ACME, limitá métodos de challenge y duración:

```json
{ "type": "ACME", "name": "acme",
  "challenges": ["dns-01"],
  "claims": { "maxTLSCertDuration": "2160h", "defaultTLSCertDuration": "2160h" } }
```

Deshabilitá provisioners no usados y `disableRenewal:false` solo donde haga falta.

## 5. Revocación (CRL / OCSP)

Habilitá CRL en el `ca.json` — el bloque va a **nivel raíz** del JSON (hermano de
`authority`/`db`, **no** dentro de `authority`, o step-ca lo ignora):

```json
{
  "db": { ... },
  "crl": { "enabled": true, "generateOnRevoke": true, "cacheDuration": "12h" },
  "authority": { ... }
}
```

> Ya viene habilitado por defecto en la intermedia principal (ver `scripts/bootstrap.sh`).
> step-ca expone el CRL (DER) en `GET /crl`; la UI lo muestra y permite descargarlo
> en **Inventario → Lista de revocación (CRL)**.

Revocar un certificado:

```bash
step ca revoke --cert miapp.crt --key miapp.key \
  --ca-url https://stepca-intermediate:9001 --root root_ca.crt
```

Publicá el CRL en un endpoint accesible por los clientes y añadí el
`crlDistributionPoints` al perfil de emisión.

## 6. Checklist de producción

- [ ] Secretos cifrados (SOPS/Vault), nada de `changeme`
- [ ] Historial git purgado de material sensible (ver `SECURITY.md`)
- [ ] Clave raíz en KMS/HSM o Root CA offline
- [ ] Imagen pineada por **digest** (ver `docs/ci.md`)
- [ ] Políticas X509/ACME restrictivas
- [ ] CRL/OCSP habilitado
- [ ] Backups cifrados y probados (`make backup` / `make restore`)
- [ ] Límites de recursos y `no-new-privileges` (`compose.prod.yaml`)
- [ ] Monitoreo activo (ver `docs/observability.md`)
