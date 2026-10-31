# Deploying to a single VPS

Why a VPS: the browser voice call is WebRTC (UDP), and the journey timers need an always-on process. Free tiers that sleep or
block UDP (Render's free tier, serverless hosts) break both. Any Linux VPS with a public IP works (Hetzner, DigitalOcean; about $5-6/month, 2 GB RAM or more
because the voice stack makes the app image about 2.5 GB).

## 1. Server and domain
1. Create an Ubuntu VPS and note its public IP.
2. Point a DNS `A` record for your domain (for example `demo.yourdomain.com`) at that IP.
3. Open the firewall: TCP 22, 80, 443 and **UDP 32768-60999** (WebRTC media uses ephemeral UDP ports).
   On Google Cloud, Oracle or AWS, allow these in the provider's firewall too; on Google Cloud that firewall is the one that matters, so you can skip `ufw`.
   ```
   sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 32768:60999/udp && sudo ufw enable
   ```
4. Install Docker: `curl -fsSL https://get.docker.com | sudo sh`

## 2. Configure
```
git clone https://github.com/Amrithesh-Kakkoth/recoverly.git && cd recoverly
cp .env.example .env
```
Edit `.env`:
- `DOMAIN=demo.yourdomain.com` and `DB_PASSWORD=<a long random password>`
- `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` (sandbox app), `PAYPAL_WEBHOOK_ID` (step 4)
- `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`
- `ABANDON_AFTER_SECONDS=90` and `TIME_SCALE=600` so a demo finishes in minutes (journey waits are divided by this, so a larger number means shorter waits)
- `DEMO_BUYER_EMAIL` / `DEMO_BUYER_PASSWORD`: the sandbox buyer shown on the Try it page
- optional: `OUTBOUND_WEBHOOK_URL` (Zapier), `TURN_ICE_URLS` / `TURN_USERNAME` / `TURN_CREDENTIAL`, Twilio settings

## 3. Start
```
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f app
```
Caddy fetches the HTTPS certificate on first request. Open `https://demo.yourdomain.com`.

## 4. PayPal webhook
In the PayPal developer dashboard (sandbox app) add a webhook to `https://demo.yourdomain.com/webhooks/paypal` for
`CHECKOUT.ORDER.APPROVED` and `PAYMENT.CAPTURE.COMPLETED`, copy its Webhook ID into `PAYPAL_WEBHOOK_ID`, then
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d app`.

## 5. Check it
- `curl https://demo.yourdomain.com/health` returns `{"ok":true}`; `curl .../api/demo-config` shows `"voice_enabled": true`.
- Run the Try it flow from your phone on mobile data. If the call connects but there is no audio, add a TURN server
  (`TURN_ICE_URLS=turns:turn.example.com:443?transport=tcp`, plus username and credential) and restart the app.

## How it is wired
`docker-compose.prod.yml` puts the app and Caddy on the host network so WebRTC media reaches the server directly; Postgres and
the dashboard listen on localhost only. `deploy/Caddyfile` sends `/api`, `/shop`, `/webhooks`, `/twilio` and `/health` to the
backend (port 8000) and everything else to the dashboard (port 3000).
