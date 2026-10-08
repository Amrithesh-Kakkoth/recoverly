# Recoverly

Callback voice agent that recovers abandoned PayPal checkouts. Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Modular monolith. Modules talk only through `app/core/events.py` (bus) and `app/core/interfaces.py`.
`voice` is the first candidate to split into its own service (swap `LiveCallRegistry` for HTTP/Redis).

| Module | Owns |
|---|---|
| `payments` | PayPal gateway, `capture_once`, family guard |
| `webhooks` | ingress, verify, dedupe, normalize |
| `journeys` | engine, timers, DSL, lint, NL compiler |
| `voice` | Pipecat bots, live registry, injection gate, tools, tagger |
| `channels` | WhatsApp (Twilio), web inbox |
| `api` | REST, SSE, storefront backend |
| `web/` | React dashboard + storefront |

## Run locally

The app targets Postgres. With Postgres running on localhost:5432 (Homebrew or Docker):

```
psql -d postgres -c "CREATE ROLE recoverly LOGIN PASSWORD 'recoverly'"
psql -d postgres -c "CREATE DATABASE recoverly OWNER recoverly"
psql -d postgres -c "CREATE DATABASE recoverly_test OWNER recoverly"
cp .env.example .env            # then fill in the PayPal sandbox and voice keys
cd backend && .venv/bin/uvicorn app.main:app --port 8000     # demo at http://localhost:8000/demo/
```

Tables are created on first boot (`create_all`); there are no migrations yet, so a schema change
needs the affected tables dropped. On boot the app also re-fires due timers, reprocesses stored
webhooks and recovers runs whose live call was cut off by the restart.

`make test` runs the suite on in-memory SQLite; `make test-pg` runs the same suite on
`recoverly_test`. Or `make up` for the Docker Compose stack.
