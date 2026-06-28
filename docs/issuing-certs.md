# Emitir certificados

La RA (`stepca-ra-one.local:9100`) expone un provisioner **ACME**. La cadena de
confianza es: cliente ← RA ← Intermediate CA ← Root CA.

> Recordá: la política de la intermedia solo permite nombres `*.local`.

## 1. Confiar en la Root CA

```bash
docker exec stepca-root cat /home/step/certs/root_ca.crt > root_ca.crt
export STEP_CA_BOOTSTRAP_URL=https://localhost:9100
```

## 2. Con `step` CLI (ACME)

```bash
step ca certificate "miapp.local" miapp.crt miapp.key \
  --provisioner acme \
  --ca-url https://stepca-ra-one.local:9100 \
  --root root_ca.crt
```

## 3. Con `certbot` (ACME)

```bash
certbot certonly --standalone \
  --server https://stepca-ra-one.local:9100/acme/acme/directory \
  -d miapp.local \
  --no-eff-email --agree-tos -m admin@example.com
```

## 4. nginx (con la cadena emitida)

```nginx
server {
    listen 443 ssl;
    server_name miapp.local;
    ssl_certificate     /etc/ssl/miapp.crt;   # incluir cadena intermedia
    ssl_certificate_key /etc/ssl/miapp.key;
}
```

## 5. Traefik (ACME automático)

```yaml
certificatesResolvers:
  stepca:
    acme:
      caServer: https://stepca-ra-one.local:9100/acme/acme/directory
      email: admin@example.com
      storage: /acme.json
      tlsChallenge: {}
```

## 6. Kubernetes (cert-manager)

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: stepca-acme
spec:
  acme:
    server: https://stepca-ra-one.local:9100/acme/acme/directory
    privateKeySecretRef:
      name: stepca-acme-account-key
    solvers:
      - http01:
          ingress:
            class: nginx
```

## Verificar una cadena emitida

```bash
step certificate verify miapp.crt --roots root_ca.crt
openssl verify -CAfile root_ca.crt -untrusted intermediate_ca.crt miapp.crt
```

## Troubleshooting

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| `acme: account does not exist` | Primer uso | El cliente crea la cuenta automáticamente; reintentar |
| Nombre rechazado | Política `*.local` de la intermedia | Usar un nombre `*.local` o ajustar la policy |
| `x509: certificate signed by unknown authority` | Falta confiar la root | Pasar `--root root_ca.crt` o instalar la root |
| RA `unhealthy` | Falta `ra.key.pem` | Ejecutar `local_scripts/key_ra.sh` |
