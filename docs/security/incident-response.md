# SaldoHelt Incident Response Plan

## Formål

Denne plan beskriver, hvordan vi reagerer, hvis SaldoHelt viser tegn på sikkerhedshændelser, nedetid eller kompromittering.

Målet er at reagere struktureret i stedet for ad hoc.

## Hvad tæller som en incident?

En incident er en hændelse, der kan påvirke fortrolighed, integritet eller tilgængelighed for SaldoHelt.

Eksempler:

- API'et er nede eller `/health` fejler
- Backend-containeren er unhealthy eller restart-looper
- FastAPI docs bliver offentligt tilgængelige i production
- Logs viser mange 5xx-fejl
- Logs viser mange 401/403 eller mistænkelige auth-fejl
- Der er mistanke om lækkede secrets
- `.env.server`, Supabase service role key eller Anthropic API key er eksponeret
- Der sker et uventet deploy i GitHub Actions
- CPU/RAM stiger unormalt uden kendt årsag
- NGINX logs viser mange gentagne scanninger eller angrebsforsøg fra samme kilde

## Roller i gruppen

Ved en incident fordeler vi rollerne sådan:

- Incident lead: koordinerer arbejdet og beslutter næste skridt
- Log ansvarlig: undersøger Docker logs, NGINX logs og Uptime Kuma
- Infrastruktur ansvarlig: tjekker Docker, NGINX, UFW og GitHub Actions
- Dokumentations ansvarlig: skriver tidslinje, observationer og handlinger

Hvis kun én person er tilgængelig, følger personen samme rækkefølge og dokumenterer undervejs.

## Fase 1: Detect

Vi opdager incidents via:

- Uptime Kuma
- Telegram alerts
- Docker healthcheck
- Docker logs
- NGINX access log
- NGINX error log
- GitHub Actions deploy history
- Brugerhenvendelser

Første kommandoer:

```bash
curl -sS https://api.saldohelt.dk/health; echo
docker compose ps
docker inspect saldohelt-backend --format 'Health={{json .State.Health}}'
docker logs --tail 100 saldohelt-backend
sudo tail -n 100 /var/log/nginx/access.log
sudo tail -n 100 /var/log/nginx/error.log
```
