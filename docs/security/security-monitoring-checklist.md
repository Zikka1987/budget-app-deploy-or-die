# SaldoHelt Security Monitoring Checklist

## Formål

Denne checklist beskriver, hvordan vi bruger monitoring og logs til at opdage unormal aktivitet, fejl eller mulige sikkerhedshændelser i SaldoHelt.

Checklistens formål er ikke at erstatte en fuld SIEM-løsning, men at give os en praktisk og realistisk metode til sikkerhedsmonitorering i vores nuværende deployment-setup.

## Monitoring-kilder

Vi bruger følgende kilder:

- Uptime Kuma
- Telegram alerts
- Docker container status
- Docker healthcheck
- Docker logs
- Docker stats
- NGINX access logs
- NGINX error logs
- GitHub Actions deploy history

## Hvad vi overvåger

### Public API health

Endpoint:

```text
https://api.saldohelt.dk/health
```

Forventet resultat:

```json
{"status":"ok"}
```

Hvis endpointet fejler, undersøger vi Docker, NGINX og seneste deploy.

### FastAPI docs disabled

Endpoint:

```text
https://api.saldohelt.dk/docs
```

Forventet resultat:

```text
404 Not Found
```

Hvis `/docs` returnerer 200 i production, er det en security regression, fordi API-dokumentationen igen er blevet offentligt tilgængelig.

### Landingpage

Endpoint:

```text
https://saldohelt.dk
```

Forventet resultat:

```text
200 OK
```

Hvis landingpagen fejler, undersøger vi NGINX, DNS, HTTPS og serverstatus.

## Daglige / manuelle checks

### Git og deployment-status

```bash
git status --short
git log -1 --oneline
```

Vi forventer clean working tree og kendt seneste commit.

### Containerstatus

```bash
docker compose ps
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
docker inspect saldohelt-backend --format 'User={{.Config.User}}'
docker inspect saldohelt-backend --format 'Health={{json .State.Health}}'
```

Forventet:

- `saldohelt-backend` er `Up`
- containeren er `healthy`
- backend kører som `appuser`
- backend er kun bundet til `127.0.0.1:8000`

### Ressourceforbrug

```bash
docker stats --no-stream
```

Vi leder efter:

- unormalt høj CPU
- unormalt høj RAM
- tegn på crash loops eller misbrug

Lavt CPU/RAM-forbrug er normal drift.

### Backend logs

```bash
docker logs --tail 100 saldohelt-backend
```

Vi leder efter:

- `500 Internal Server Error`
- `Traceback`
- `Exception`
- mange `401`
- mange `403`
- gentagne fejl på samme endpoint
- tegn på at `/docs`, `/redoc` eller `/openapi.json` bliver ramt

### NGINX access log

```bash
sudo tail -n 150 /var/log/nginx/access.log
```

Målrettet søgning efter scanninger:

```bash
sudo grep -Ei '(\.env|\.git|docker-compose|phpinfo|server-status|telescope|wp-admin|wp-login|vendor/phpunit|cgi-bin|bin/sh)' /var/log/nginx/access.log | tail -n 80
```

Vi leder efter:

- scanning efter `.env`
- scanning efter `.git/config`
- scanning efter `docker-compose.yml`
- WordPress/PHP-scanninger
- path traversal mod `cgi-bin`
- mange gentagne requests fra samme IP

Enkelte 404-scanninger er normal internetstøj. Mange gentagne scanninger fra samme IP kan være en potentiel incident.

### Statuskode-optælling

```bash
sudo awk '$9 ~ /^[0-9][0-9][0-9]$/ {print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -nr
```

Vi holder især øje med:

- mange `500`, `502`, `503`, `504`
- mange `401`
- mange `403`
- stor stigning i `404`

### Top paths

```bash
sudo awk '{print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -nr | head -30
```

Vi forventer at se mange requests mod:

- `/`
- `/health`
- `/docs` fra Uptime Kuma

Mistænkelige paths kan være:

- `/.env`
- `/.git/config`
- `/docker-compose.yml`
- `/phpinfo.php`
- `/vendor/phpunit/...`
- `/wp-login.php`

### Top IP-adresser

```bash
sudo awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -nr | head -20
```

Vi forventer, at interne monitors kan fylde meget.

Hvis én ekstern IP laver mange mistænkelige requests på kort tid, vurderer vi om det kræver containment.

### NGINX error log

```bash
sudo tail -n 120 /var/log/nginx/error.log
```

Vi leder efter:

- upstream errors
- timeout
- SSL/certifikatfejl
- permission errors
- NGINX-fejl ved reload

Tom error log er normal og ønsket.

## Firewall og eksponering

```bash
sudo ufw status verbose
ss -tulpn | grep -E ':22|:80|:443|:8000|:3001|:5432'
docker ps --format "table {{.Names}}\t{{.Ports}}"
sudo nginx -t
```

Forventet:

- UFW tillader kun `22`, `80` og `443`
- backend kører kun på `127.0.0.1:8000`
- Uptime Kuma kører kun på `127.0.0.1:3001`
- Postgres demo kører kun på `127.0.0.1:5432`
- NGINX config er valid

## Klassifikation af observationer

| Observation | Klassifikation | Handling |
| --- | --- | --- |
| Enkelte 404 mod `.env`, `.git`, `phpinfo` | Normal internetstøj | Ingen akut handling |
| Mange scanninger fra én ekstern IP | Potentiel incident | Undersøg og overvej blokering |
| Mange 5xx | Incident | Tjek Docker logs, NGINX error log og seneste deploy |
| `/health` fejler | Incident | Tjek Uptime Kuma, Docker, NGINX og GitHub Actions |
| `/docs` returnerer 200 | Security regression | Ret production config eller rollback |
| Container unhealthy | Incident | Tjek logs, redeploy eller rollback |
| Uventet deploy | Potentiel incident | Tjek GitHub Actions, commit history og adgang |
| Mistanke om lækkede secrets | Kritisk incident | Rotér secrets og redeploy |

## Baseline-observation fra Dag 14

Ved vores Dag 14-gennemgang så vi:

- Backend var healthy
- API `/health` returnerede 200
- `/docs` returnerede 404
- Landingpage returnerede 200
- Security headers var aktive
- CPU/RAM-forbrug var lavt
- NGINX error log var tom
- Der var ingen 5xx, 401 eller 403
- Der var scanninger mod `.env`, `.git/config`, PHP/WordPress paths og `cgi-bin`

Vurdering:

```text
Normal drift med forventet internet-scanning.
Ingen aktiv incident.
Ingen containment nødvendig.
Observationen dokumenteres som sikkerhedsrelevant loganalyse.
```
