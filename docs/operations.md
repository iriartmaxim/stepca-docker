# Operación

## Backup y restore

```bash
make backup                                   # snapshot consistente en backups/
make restore FILE=backups/stepca-XXXX.tar.gz  # restaura un backup
```

- `backup.sh` detiene brevemente los servicios para que la DB **badger** quede
  consistente (overridable con `NO_STOP=1`, menos seguro).
- Rota backups: conserva los `KEEP` más recientes (default 7).
- ⚠️ Los backups contienen **claves privadas**: guardalos cifrados y fuera de git
  (`backups/` está en `.gitignore`).

Programar a diario (cron del host):

```cron
0 3 * * *  cd /ruta/al/repo && make backup >> /var/log/stepca-backup.log 2>&1
```

## Renovación de la CA intermedia

La intermedia vence en 2035, pero conviene renovarla automáticamente antes del
umbral:

```bash
make renew                       # renueva si quedan <30 días (RENEW_THRESHOLD_DAYS)
```

Timer systemd (ejemplo):

```ini
# /etc/systemd/system/stepca-renew.service
[Service]
Type=oneshot
WorkingDirectory=/ruta/al/repo
ExecStart=/usr/bin/make renew

# /etc/systemd/system/stepca-renew.timer
[Timer]
OnCalendar=weekly
Persistent=true
[Install]
WantedBy=timers.target
```

## Logging estructurado

Por defecto los `ca.json` usan `"logger": {"format": "text"}`. Para agregadores
(Loki, ELK) cambialo a JSON:

```json
"logger": { "format": "json" }
```

La rotación de logs de Docker está configurada en `compose.prod.yaml`
(`json-file`, `max-size: 10m`, `max-file: 3`). Para enviar a un colector,
añadí un driver de logging (p. ej. `loki` o `fluentd`) en el override de prod.

## Producción

```bash
make prod    # docker compose -f compose.yaml -f compose.prod.yaml up -d
```

El override de prod añade límites de CPU/memoria, `no-new-privileges`, rotación de
logs y **no publica la Root CA** al host. Ver `docs/hardening.md` para el patrón
de **Root CA offline**.
