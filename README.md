# Recoverly

Callback voice agent that recovers abandoned PayPal checkouts. Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

When a PayPal checkout is abandoned, a WhatsApp nudge goes out, then an AI voice agent calls the customer, answers
objections, and sends a fresh PayPal link while they stay on the line. When PayPal confirms the payment, that event is pushed
into the live call and the agent confirms it out loud. Merchants describe the flow in plain English and watch recovered
revenue on a live dashboard.

## How it uses PayPal (sandbox only)

- **PayPal Agent Toolkit (Python):** creates and looks up orders and returns the approval link the agent sends to the customer.
- **PayPal REST API (Orders v2):** captures payments with `PayPal-Request-Id` idempotency keys, refunds, and webhook signature
  verification. One `capture_once` path plus a per-customer "family" guard prevents double charges.
- **PayPal Checkout and webhooks** (`CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.COMPLETED`): verified, deduplicated, then injected
  into the live call. The app refuses to start unless the PayPal base URL is the sandbox.

## How it uses AI

- **LLM (OpenAI-compatible, default `gpt-4.1-mini`):** the voice agent's brain (function calling: send link, check payment, apply a
  capped offer, end call); compiles plain-English journeys into validated JSON; tags each call's outcome.
- **Pipecat** runs the real-time voice pipeline (WebRTC in the browser, Twilio Media Streams for real phone calls), with
  **Deepgram** (speech-to-text), **Cartesia** (text-to-speech) and **Silero VAD** (turn detection).

## Other tools and sponsor integrations

- **Zapier:** outbound webhook when a recovery run ends (see Integrations below).
- **Postman:** collection and environment in `docs/postman/`, including the PayPal sandbox calls.
- **AG Grid:** the dashboard's runs table.
- **Stack:** Python, FastAPI, SQLAlchemy, Postgres, Next.js, React, TypeScript, Tailwind, server-sent events, Twilio, Docker Compose.

Licensed under MIT.

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
| `accounts` | merchants, password hashing, sessions, the demo merchant |
| `web/` | Next.js merchant dashboard (runs, KPIs, journey builder) and the public "Try it" wizard |

## Run locally

The app targets Postgres. With Postgres running on localhost:5432 (Homebrew or Docker):

```
psql -d postgres -c "CREATE ROLE recoverly LOGIN PASSWORD 'recoverly'"
psql -d postgres -c "CREATE DATABASE recoverly OWNER recoverly"
psql -d postgres -c "CREATE DATABASE recoverly_test OWNER recoverly"
cp .env.example .env            # then fill in the PayPal sandbox and voice keys
cd backend && .venv/bin/uvicorn app.main:app --port 8000
```

The dashboard is a separate Next.js app that proxies `/api` and `/shop` to the backend (`BACKEND_URL`, default `http://localhost:8000`):

```
cd web && npm install && npm run dev      # http://localhost:3000  (sign up, or /try for the public demo)
```

The journey builder's "Generate" button needs an LLM key (`OPENAI_API_KEY` or `LLM_API_KEY`).

Tables are created on first boot (`create_all`); there are no migrations yet, so a schema change
needs the affected tables dropped. On boot the app also re-fires due timers, reprocesses stored
webhooks and recovers runs whose live call was cut off by the restart.

`make test` runs the suite on in-memory SQLite; `make test-pg` runs the same suite on
`recoverly_test`.

### Accounts

Merchants sign up with an email and password at `/signup`, and each one only sees its own runs, calls, journeys and KPIs.
Passwords are hashed with scrypt, and sessions are HttpOnly cookies backed by the database. There is no password reset yet.
`/try` needs no account: those runs belong to a demo merchant (`DEMO_MERCHANT_EMAIL`), which can only be signed in to if
`DEMO_MERCHANT_PASSWORD` is set. A signed-in merchant's own `/try` checkouts count as that merchant's.
`OUTBOUND_WEBHOOK_URL` only receives the demo merchant's results, since it isn't per merchant yet.

### Integrations

- **Zapier (or any webhook):** set `OUTBOUND_WEBHOOK_URL` to a Zapier "Catch Hook" URL. When a recovery run ends the backend POSTs
  `{event: recovery.recovered | recovery.lost, run_id, customer_name, amount, currency, text, run_url}` (never the phone number), so a Zap
  can post "Recovered USD 49.00 from Asha" to Slack, a sheet or email. `POST /api/integrations/webhook/test` sends a sample so the Zap
  can learn the fields. Failures are retried briefly and never affect recovery.
- **Postman:** import `docs/postman/recoverly.postman_collection.json` and `recoverly-local.postman_environment.json`. It covers the
  storefront, runs, calls, metrics, journeys, integrations and the PayPal sandbox calls (OAuth, create, get, capture), with tests; put
  your sandbox client id and secret in the environment (kept out of git).
- **AG Grid:** the dashboard's runs table (sorting, per-column filters, quick search) is AG Grid Community.

### Real phone calls (Twilio)

By default the call rings in the browser. To ring a real handset instead:

1. Twilio account and a voice-capable number; on a trial account, verify your own phone as a caller ID.
2. Expose the backend publicly over https (`ngrok http 8000`) and set `PUBLIC_BASE_URL` to that address.
3. In `.env`: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VOICE_FROM=+1...`, `CALL_VIA_PHONE=true`, plus the voice keys.
4. Enter your verified phone number in the checkout form (E.164, e.g. `+919876543210`) and tick the call consent box.

Twilio calls the app back at `/twilio/voice/{call_id}` (TwiML) and `/twilio/status/{call_id}`, then streams audio to
`/twilio/ws`; each call has its own token and the webhooks verify Twilio's signature. Trial calls play a short
"trial account" message first, and calling Indian mobiles from a US number may be filtered as spam.

### Deploying

See [docs/DEPLOY.md](docs/DEPLOY.md) for a single-VPS setup with HTTPS (Caddy), WebRTC-friendly networking, and CI/CD through GitHub Actions.

### Docker Compose

`make up` builds and starts Postgres 16, the app and the Next.js dashboard (`WEB_PORT`, default 3000) (image is about 2.5 GB because of the voice
stack). If a local Postgres or server already uses the default ports:

```
DB_PORT=5433 APP_PORT=8001 docker compose up -d --build
docker compose exec app pytest -q          # the suite, inside the container
```

Browser calls into a container on Docker Desktop (macOS/Windows) are untested: WebRTC media needs
UDP reachability, which normally means a TURN server or host networking on a Linux VPS.
