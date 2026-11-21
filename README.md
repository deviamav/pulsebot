# PulseBot

> **CV theme:** Automation & Integration Platform (Telegram bridge)  
> **Repo:** [deviamav/pulsebot](https://github.com/deviamav/pulsebot)

**PulseBot** is a production-style **Telegram task bridge** between clients and designers. All communication runs **through the bot**: neither side sees the other’s Telegram username, numeric ID, or profile. Files are relayed via `copyMessage` / `file_id` to preserve sender anonymity. Access is **invite-code only** — admins issue one-time codes with role and expiry.

## Features

- **Closed access via invite codes** — without a valid code, users see “access restricted”
- Roles: `ADMIN`, `CUSTOMER`, `DESIGNER` with checks at handler, service, and repository layers
- FSM task creation wizard: title → description → priority → deadline → designer → files → confirm
- Task statuses with allowed transitions per role (`NEW` … `DONE`)
- Inline task cards, anonymous comments (role-only attribution), attachments (photo, PDF, ZIP, PSD, etc.)
- Confirmation step for destructive actions (close task, ban user, revoke invite)
- Reply keyboard menus per role; pagination on lists
- Deadline reminders (24h, 2h, overdue)
- **Redis rate limiting** per user; FSM storage in Redis
- Structured JSON logging (structlog), `/healthz` and `/readyz` for Docker
- Graceful shutdown (SIGTERM/SIGINT)

## Stack

- Python **3.12** · **aiogram 3** · **asyncpg** · SQLAlchemy 2.0 async · Alembic
- PostgreSQL 16 · Redis 7
- Pydantic Settings · aiohttp health endpoint
- Docker Compose

## Project layout

```
app/
├── api/              # healthcheck
├── bot/              # handlers, keyboards, middlewares, FSM states
├── core/             # config, logging
├── db/models/        # User, Task, Comment, Attachment, InviteCode
├── repositories/
└── services/
migrations/           # Alembic
```

## Quick start (Docker)

```bash
cp .env.example .env
# BOT_TOKEN from @BotFather; ADMIN_IDS=comma-separated Telegram user IDs

docker compose up -d --build
docker compose logs -f bot
```

Health: `http://127.0.0.1:8080/healthz`, `http://127.0.0.1:8080/readyz`.

Users in `ADMIN_IDS` become `ADMIN` on first `/start`. They can create invite codes for `CUSTOMER` / `DESIGNER` roles.

## Local development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# POSTGRES_HOST=localhost, REDIS_HOST=localhost

docker compose up -d postgres redis
alembic upgrade head
python -m app
```

## Environment

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | BotFather token |
| `ADMIN_IDS` | Bootstrap admin Telegram IDs |
| `POSTGRES_*` | Database |
| `REDIS_*` | FSM + throttling |
| `RATE_LIMIT_PER_SECOND` | Default `2` |

See `.env.example` for placeholders only.

## Migrations

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

Migrations run automatically in the Docker `bot` container before start.

## Production notes

- Long polling by default; optional reverse proxy only needed for health HTTP
- Back up the `postgres_data` volume
- JSON logs suit Loki / ELK; probe `/readyz` for uptime checks

Example nginx (health only):

```nginx
server {
    listen 80;
    server_name pulsebot.example.com;
    location /healthz {
        proxy_pass http://127.0.0.1:8080/healthz;
    }
}
```

## Security & anonymity

- Media uses `copyMessage` (no “forwarded from” exposure)
- Formatters never print Telegram IDs or usernames to the other party
- Parameterized SQL via SQLAlchemy 2.0

## License

Portfolio / demonstration use.