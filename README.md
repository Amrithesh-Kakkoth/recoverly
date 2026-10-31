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
| `web/` | Next.js dashboard (runs, KPIs, journey builder) and the "Try it" wizard; `web/demo` is the older static page |

## Run locally

The app targets Postgres. With Postgres running on localhost:5432 (Homebrew or Docker):

```
psql -d postgres -c "CREATE ROLE recoverly LOGIN PASSWORD 'recoverly'"
psql -d postgres -c "CREATE DATABASE recoverly OWNER recoverly"
psql -d postgres -c "CREATE DATABASE recoverly_test OWNER recoverly"
cp .env.example .env            # then fill in the PayPal sandbox and voice keys
cd backend && .venv/bin/uvicorn app.main:app --port 8000     # demo at http://localhost:8000/demo/
```

The dashboard is a separate Next.js app that proxies `/api` and `/shop` to the backend (`BACKEND_URL`, default `http://localhost:8000`):

```
cd web && npm install && npm run dev      # http://localhost:3000  (Journeys, Try it)
```

The journey builder's "Generate" button needs an LLM key (`OPENAI_API_KEY` or `LLM_API_KEY`).

Tables are created on first boot (`create_all`); there are no migrations yet, so a schema change
needs the affected tables dropped. On boot the app also re-fires due timers, reprocesses stored
webhooks and recovers runs whose live call was cut off by the restart.

`make test` runs the suite on in-memory SQLite; `make test-pg` runs the same suite on
`recoverly_test`.

### Real phone calls (Twilio)

By default the call rings in the browser. To ring a real handset instead:

1. Twilio account and a voice-capable number; on a trial account, verify your own phone as a caller ID.
2. Expose the backend publicly over https (`ngrok http 8000`) and set `PUBLIC_BASE_URL` to that address.
3. In `.env`: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VOICE_FROM=+1...`, `CALL_VIA_PHONE=true`, plus the voice keys.
4. Enter your verified phone number in the checkout form (E.164, e.g. `+919876543210`) and tick the call consent box.

Twilio calls the app back at `/twilio/voice/{call_id}` (TwiML) and `/twilio/status/{call_id}`, then streams audio to
`/twilio/ws`; each call has its own token and the webhooks verify Twilio's signature. Trial calls play a short
"trial account" message first, and calling Indian mobiles from a US number may be filtered as spam.

### Docker Compose

`make up` builds and starts Postgres 16, the app and the Next.js dashboard (`WEB_PORT`, default 3000) (image is about 2.5 GB because of the voice
stack). If a local Postgres or server already uses the default ports:

```
DB_PORT=5433 APP_PORT=8001 docker compose up -d --build
docker compose exec app pytest -q          # the suite, inside the container
```

Browser calls into a container on Docker Desktop (macOS/Windows) are untested: WebRTC media needs
UDP reachability, which normally means a TURN server or host networking on a Linux VPS.
