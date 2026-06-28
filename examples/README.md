# Ejemplos de integración de clientes

Certificados emitidos por la RA (`stepca-ra-one.local:9100`, provisioner ACME).
Recordá: la política de la intermedia solo permite nombres `*.local`.

| Archivo | Uso |
|---------|-----|
| [cert-manager-clusterissuer.yaml](cert-manager-clusterissuer.yaml) | `ClusterIssuer` + `Certificate` para Kubernetes |
| [traefik-dynamic.yml](traefik-dynamic.yml) | Resolver ACME y router en Traefik |
| [nginx.conf](nginx.conf) | TLS en nginx con un cert ya emitido |
| [acme/demo-http01.sh](acme/demo-http01.sh) | Demo E2E del challenge http-01 |

Tipos de challenge ACME (http-01, dns-01, tls-alpn-01, device-attest-01):
ver [../docs/acme-challenges.md](../docs/acme-challenges.md).

Para los comandos de emisión (`step`, `certbot`) ver
[../docs/issuing-certs.md](../docs/issuing-certs.md).
