# Escalabilidad

## Múltiples Registration Authorities (multi-tenant)

Cada RA es un servicio independiente en modo `stepcas` que delega en la misma
intermedia. Para agregar `ra-two`, replicá el patrón de `stepca-ra-one.local`:

```yaml
  stepca-ra-two.local:
    image: ${STEPCA_IMAGE:-smallstep/step-ca:0.28.3}
    container_name: stepca-ra-two.local
    hostname: stepca-ra-two.local
    depends_on:
      stepca-intermediate: { condition: service_healthy }
    environment:
      CA_URL: https://stepca-intermediate:9000/health
    volumes:
      - ./persistent/ra/ra-two/config:/home/step/config
      - ./persistent/ra/ra-two/certs:/home/step/certs
      - ./persistent/ra/ra-two/secrets:/home/step/secrets
    ports: ["9101:9100"]
    command: sh -c "step-ca /home/step/config/ca.json"
```

Pasos por cada RA nueva:
1. Crear un provisioner JWK en la intermedia: `step ca provisioner add ra2_jwk --type JWK --create`.
2. Generar su `ra.key.pem` (adaptar `local_scripts/key_ra.sh` con el nombre del provisioner).
3. Copiar la estructura `persistent/ra/ra-two/` y su `ca.json`.

> Tip: parametrizá esto con un script generador o, mejor, usá el Helm chart
> (`charts/stepca/`) que ya soporta N réplicas de RA por `values.yaml`.

## Alta disponibilidad de la intermedia (DB externa)

El badger embebido no permite múltiples réplicas escribiendo la misma DB. Para HA,
migrá a **PostgreSQL**:

```bash
docker compose -f compose.yaml -f compose.ha.yaml up -d
```

Y en el `ca.json` de la intermedia:

```json
"db": {
  "type": "postgresql",
  "dataSource": "postgresql://stepca:PASS@postgres:5432/stepca"
}
```

Con la DB externalizada podés correr varias réplicas de la intermedia detrás de un
balanceador (round-robin TCP/TLS passthrough). La Root sigue siendo única y offline.

## Kubernetes

Ver `charts/stepca/` para desplegar en K8s con Helm (StatefulSets para las CAs,
Secrets para las contraseñas, Service/Ingress para ACME).
