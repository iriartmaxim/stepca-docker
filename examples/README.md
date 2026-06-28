# Ejemplos de integración de clientes

Certificados emitidos por la RA (`stepca-ra-one.local:9100`, provisioner ACME).
Recordá: la política de la intermedia solo permite nombres `*.local`.

| Archivo | Uso |
|---------|-----|
| [cert-manager-clusterissuer.yaml](cert-manager-clusterissuer.yaml) | `ClusterIssuer` + `Certificate` para Kubernetes |
| [traefik-dynamic.yml](traefik-dynamic.yml) | Resolver ACME y router en Traefik |
| [nginx.conf](nginx.conf) | TLS en nginx con un cert ya emitido |
| [acme/demo-http01.sh](acme/demo-http01.sh) | Demo E2E http-01 (step standalone) |
| [acme/demo-tlsalpn01.sh](acme/demo-tlsalpn01.sh) | Demo E2E tls-alpn-01 (lego) |
| [acme/demo-dns01.sh](acme/demo-dns01.sh) | Demo E2E dns-01 (CoreDNS + lego) |
| [acme/demo-deviceattest01.sh](acme/demo-deviceattest01.sh) | Scaffold device-attest-01 (TPM) |

Infraestructura del demo dns-01: `../compose.acme-demo.yaml` (CoreDNS) y
`acme/coredns/`. Detalle de los 4 tipos: [../docs/acme-challenges.md](../docs/acme-challenges.md).

Para los comandos de emisión (`step`, `certbot`) ver
[../docs/issuing-certs.md](../docs/issuing-certs.md).
