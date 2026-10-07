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

```
cp .env.example .env && make up
```
