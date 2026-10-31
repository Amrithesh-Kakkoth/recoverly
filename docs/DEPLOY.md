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
Set up [CI/CD](#cicd-github-actions) below and run the **Deploy** workflow. To build on the server instead (slower, no rollback):
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

## CI/CD (GitHub Actions)
| Workflow | Runs | Does |
|---|---|---|
| `CI` | every PR and push to `main` | backend tests on SQLite and Postgres, web build and typecheck, Postman contract run, secret scan |
| `Docker check` | PRs that touch images or Compose | validates Compose and builds both images |
| `Publish images` | push to `main` | pushes `ghcr.io/amrithesh-kakkoth/recoverly-{app,web}` tagged with the commit SHA and `latest` |
| `Deploy` | by hand (Actions tab) | pulls one commit's images on the server, checks health, rolls back on failure |

CI uses no real API keys and calls no paid service. `.env` stays on the server. Deploying restarts the backend and drops any call in
progress, so avoid deploying during judging unless you need to. A schema change still means dropping tables by hand, because there
are no migrations yet.

One-time setup:
1. On the server, let your user run Docker, then log out and back in: `sudo usermod -aG docker $USER`
2. On your own machine, make a key used only for deploys: `ssh-keygen -t ed25519 -f recoverly_deploy -N ""`. Add the contents of
   `recoverly_deploy.pub` to `~/.ssh/authorized_keys` on the server.
3. In GitHub go to **Settings → Environments**, create `production`, and optionally add yourself as a required reviewer.
4. In that environment add these **secrets**: `DEPLOY_HOST` (server IP), `DEPLOY_USER`, `DEPLOY_SSH_KEY` (contents of `recoverly_deploy`),
   and `DEPLOY_KNOWN_HOSTS` (output of `ssh-keyscan -t ed25519 <server IP>`, checked against the server's real key).
5. Add these **variables**: `DEPLOY_URL` (`https://demo.yourdomain.com`), and `DEPLOY_PATH` if the repo isn't at `~/recoverly`.
6. Once CI has run once, go to **Settings → Branches** and protect `main`: require a PR and these checks: `Backend tests (sqlite)`,
   `Backend tests (postgres)`, `Web build and typecheck`, `API contract (Postman)`, `Secret scan`.

To deploy: **Actions → Deploy → Run workflow**. Leave the SHA blank for the latest commit, after `Publish images` has finished for it.
To roll back by hand, run it again with an earlier commit's SHA.
