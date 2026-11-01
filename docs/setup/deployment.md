# Deployment

How to serve CARA to a team from one machine: making it reachable, sizing it, securing it, and keeping its data
safe across upgrades.

!!! info "Before you begin"
    CARA runs with Docker Compose on the server ([Installation](../get-started/installation.md)).

## Opening it to the network

The web app listens on port 8501 of every network interface; the API and the database listen on the machine
itself only. Set the name people use to reach the server in `.env`, then restart:

```bash
CARA_PUBLIC_HOST=cara.example.org
```

```bash
docker compose up -d
```

Annotators then open `http://cara.example.org:8501`. Their accounts are created by an admin, under **Study
settings** in a study's header ([Name and team](../study/new-study.md#6-name-and-team)).

## HTTPS

Logins travel in the clear over plain HTTP. On any network you don't fully trust, put a reverse proxy with a
certificate in front of the web app. With [Caddy](https://caddyserver.com/), which fetches the certificate by
itself, the whole configuration is:

```text
cara.example.org {
    reverse_proxy localhost:8501
}
```

The proxy must pass WebSocket connections through, which Caddy does by default; nginx needs the `Upgrade` and
`Connection` headers set. Then close port 8501 to the outside, so the proxy is the only way in.

## Server settings

Set in `.env` (the template is `.env.example`); restart with `docker compose up -d` after a change.

| Variable | Default | Meaning |
|---|---|---|
| `CARA_SECRET_KEY` | required | Signs login tokens: a random string of 32 or more characters (`openssl rand -hex 32`). Changing it logs everyone out. |
| `CARA_ADMIN_USERNAME`, `CARA_ADMIN_PASSWORD` | `admin`, set by `quickstart.sh` | The first superuser, created when the API starts on a database without users. |
| `CARA_PUBLIC_HOST` | `localhost` | The name people open the web app by. |
| `POSTGRES_PASSWORD` | `cara` | The database password. |
| `CARA_WORKERS` | `4` | API processes. |
| `CARA_DB_POOL_SIZE`, `CARA_DB_MAX_OVERFLOW` | `10`, `10` | Database connections per API process; keep `CARA_WORKERS` × (pool + overflow) under Postgres' limit of 100. |
| `CARA_TOKEN_MINUTES` | `720` | How long a login lasts. |
| `HF_TOKEN` | empty | For gated models when encoding ([Encoding](encoding.md#models-and-access-tokens)). |

CARA sends no usage statistics and makes no outbound calls, except model downloads when you encode.

## Capacity

Every click is saved at once, so nothing is lost when a browser closes, and annotators resume where they left
off. Measured on one 12-core machine with the defaults:

| | 10 users | 50 users | 100 users |
|---|---|---|---|
| Saves per second, users clicking without pause | 333 | 318 | 275 |
| Save latency, 95th percentile | 59 ms | 217 ms | 481 ms |

The web app is the tighter limit, because every browser session runs in one Python process: when 10 people open a
200-image query at the same moment, the page takes about 6 s to appear, and clicks afterwards about 0.2 s. For
larger teams, run several `frontend` containers behind a load balancer with sticky sessions.

## Backups

All of CARA's state (accounts, studies, judgments, the action log and the embeddings) is in Postgres; the images
stay in `data/`. Back up the database while CARA runs:

```bash
docker compose exec -T db pg_dump -U cara -Fc cara > cara-$(date +%F).dump
```

To restore a backup into a fresh database:

```bash
docker compose down -v && docker compose up -d db
docker compose exec -T db pg_restore -U cara -d cara --no-owner < cara-2026-11-02.dump
docker compose up -d
```

!!! warning
    `docker compose down -v` deletes the database volume. Run it only to restore a backup you have checked.

## Upgrading

```bash
docker compose exec -T db pg_dump -U cara -Fc cara > cara-before-upgrade.dump
git pull
docker compose up -d --build
```

The API applies any database migrations when it starts, so an upgrade needs no further step. The
[release notes](../help/release-notes.md) list what changed.
