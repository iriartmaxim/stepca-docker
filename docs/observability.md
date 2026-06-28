# Observabilidad

## Habilitar métricas en step-ca

Añadí el bloque `metrics` al `ca.json` de la intermedia/RA:

```json
"metrics": { "enabled": true }
```

step-ca expone entonces métricas Prometheus en `/metrics`.

## Levantar Prometheus + Grafana

```bash
docker compose -f compose.yaml -f observability/compose.observability.yaml up -d
```

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (usuario `admin`, pass `GRAFANA_PASSWORD`)

El dashboard `observability/grafana-dashboard.json` muestra CAs activas,
tasa de emisión, latencia p95 de firma y errores 5xx. Importalo en Grafana o
provisioná el directorio de dashboards.

## Alertas recomendadas

| Alerta | Expresión (PromQL) |
|--------|--------------------|
| CA caída | `up{job=~"stepca.*"} == 0` |
| Pico de errores | `rate(step_ca_requests_total{code=~"5.."}[5m]) > 0.1` |
| Latencia alta | `histogram_quantile(0.95, rate(step_ca_request_duration_seconds_bucket[5m])) > 1` |
| Intermedia por vencer | exportar días-a-expiración con un side-car y alertar < 30d |
