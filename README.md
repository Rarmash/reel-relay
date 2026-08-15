# Reel Relay

A small FastAPI backend that downloads public Instagram Reels for iOS Shortcuts and streams MP4 files back to the caller. Video files live only in a per-request tmpfs directory and are removed after completion, cancellation, or error. SQLite stores token hashes and aggregate usage events—never Reel URLs or metadata.

## Deploy

Prerequisites: Docker Engine, Docker Compose, an `A`/`AAAA` DNS record for `reels.rarmash.ru`, and the existing Nginx installation on the VPS.

```bash
git clone YOUR_REPOSITORY_URL reel-relay
cd reel-relay
cp .env.example .env
openssl rand -hex 32
nano .env                  # paste the result as ADMIN_TOKEN
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8765/health
```

Create a separate Nginx virtual host using `nginx.conf.example`; do not change the server block for the other domain. Nginx can serve both domains on the same ports 80 and 443 using the request hostname and TLS SNI. The application port 8765 remains bound exclusively to `127.0.0.1` and must not be exposed through UFW.

Allow SSH and the two shared public Nginx ports. These UFW rules are idempotent, so they are safe if 80/443 are already allowed:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp comment 'Nginx HTTP'
sudo ufw allow 443/tcp comment 'Nginx HTTPS'
sudo ufw status verbose
# Run this only if UFW is currently inactive, after confirming the SSH rule:
sudo ufw enable
```

Install Certbot's Nginx integration if necessary, copy the example as a new site, and enable it:

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
sudo cp nginx.conf.example /etc/nginx/sites-available/reels.rarmash.ru
sudo ln -s /etc/nginx/sites-available/reels.rarmash.ru /etc/nginx/sites-enabled/reels.rarmash.ru
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d reels.rarmash.ru
sudo nginx -t
sudo systemctl reload nginx
curl https://reels.rarmash.ru/health
```

Create user tokens as needed. Each plaintext token is returned once; save it immediately in the corresponding Shortcut:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/admin/tokens \
  -H "Authorization: Bearer ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"user-one"}'

curl -X POST http://127.0.0.1:8765/api/v1/admin/tokens \
  -H "Authorization: Bearer ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"user-two"}'
```

Download a public Reel:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/download \
  -H "Authorization: Bearer USER_TOKEN" -H "Content-Type: application/json" \
  -d '{"url":"https://www.instagram.com/reel/XXXXXXXX/"}' -o reel.mp4
```

List tokens, inspect this month's traffic, and revoke a token:

```bash
curl -H "Authorization: Bearer ADMIN_TOKEN" http://127.0.0.1:8765/api/v1/admin/tokens
curl -H "Authorization: Bearer ADMIN_TOKEN" http://127.0.0.1:8765/api/v1/admin/stats
curl -X POST -H "Authorization: Bearer ADMIN_TOKEN" http://127.0.0.1:8765/api/v1/admin/tokens/1/revoke
docker compose logs -f --tail=100 app
```

See `docs/shortcut.md` for iOS configuration.

## Configuration and maintenance

`.env.example` documents all limits. The sixth download waits asynchronously for a semaphore slot. The timeout covers `yt-dlp`; the tmpfs size is an independent hard ceiling. SQLite uses WAL and short atomic insert transactions.

Update `yt-dlp` by changing its pinned version in `requirements.txt`, then rebuild:

```bash
docker compose build --pull --no-cache app
docker compose up -d app
```

Optional future cookies can be supplied through the commented read-only mount in `compose.yaml`; do not commit them. The service runs as UID 10001 with a read-only root filesystem, no Linux capabilities, and a persistent volume only for SQLite.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
ADMIN_TOKEN=test pytest -q
```

Tests mock the downloader and do not contact Instagram. A real Instagram download has not been validated by this test suite.
