# Deploy: Second Brain on Ubuntu 22.04 (Timeweb Cloud Server)

Target setup:

- **Host:** Timeweb Cloud Server (VPS), Ubuntu 22.04
- **App:** uvicorn (FastAPI) bound to `127.0.0.1:8000`, managed by systemd
- **Reverse proxy:** nginx, HTTPS via Let's Encrypt (certbot)
- **Code:** `/opt/second-brain/`
- **Data:** `/opt/second-brain/data/brain.json` (persistent — survives restarts and redeploys)
- **Secrets:** `/opt/second-brain/.env`, loaded by systemd via `EnvironmentFile`
- **Updates:** `git pull && systemctl restart second-brain`

> Why VPS and not Timeweb App Platform: App Platform's persistent-storage
> story for FastAPI apps isn't documented as of the time of writing, and
> `brain.json` is the single source of truth — losing it on redeploy is
> not acceptable. A regular Cloud Server gives a normal disk.

---

## 1. Local prep

```bash
# Generate the bcrypt hash for your password (keep the output safe)
python scripts/hash_password.py 'your-strong-password'
# → $2b$12$...
```

Generate a random 64-hex-char string for `SESSION_SECRET` (not currently
used by the code but reserved for future cookie signing):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Push your code to GitHub if you haven't already.

---

## 2. Provision the VPS

In Timeweb Cloud panel: **Cloud Servers → Create** → Ubuntu 22.04,
minimum 1 vCPU / 1 GB RAM is fine for a single user. Note the IP. Point
your DNS A record (e.g. `brain.example.com`) at it.

SSH in as root:

```bash
ssh root@<your-server-ip>
```

---

## 3. System packages

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git nginx certbot \
               python3-certbot-nginx ufw

# Basic firewall
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
```

---

## 4. App user and code

```bash
# Dedicated unprivileged user
adduser --system --group --home /opt/second-brain --shell /bin/bash brain

# Code
cd /opt/second-brain
sudo -u brain git clone https://github.com/<you>/second-brain-graph.git .

# Python venv + deps
sudo -u brain python3 -m venv venv
sudo -u brain ./venv/bin/pip install --upgrade pip
sudo -u brain ./venv/bin/pip install -r requirements.txt
sudo -u brain ./venv/bin/pip install 'openai>=1.40'   # if you use cloud Whisper

# Data dir
mkdir -p /opt/second-brain/data
chown brain:brain /opt/second-brain/data
```

---

## 5. Environment file

```bash
sudo -u brain tee /opt/second-brain/.env > /dev/null <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

APP_USERNAME=maksim
APP_PASSWORD_HASH=$2b$12$...   # from `scripts/hash_password.py`

ALLOWED_HOSTS=brain.example.com
FORWARDED_ALLOW_IPS=127.0.0.1

STORAGE_PATH=/opt/second-brain/data/brain.json

HOST=127.0.0.1
PORT=8000
EOF

chmod 600 /opt/second-brain/.env
```

⚠️ `.env` contains secrets — never commit it. The file is owned by
`brain:brain` with mode 600 so only that user (and root) can read it.

---

## 6. systemd service

```bash
cat > /etc/systemd/system/second-brain.service <<'EOF'
[Unit]
Description=Second Brain (FastAPI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=brain
Group=brain
WorkingDirectory=/opt/second-brain
EnvironmentFile=/opt/second-brain/.env
ExecStart=/opt/second-brain/venv/bin/python -u app.py
Restart=on-failure
RestartSec=5

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/second-brain/data /opt/second-brain
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now second-brain
systemctl status second-brain   # expect: active (running)
```

Logs live in journald:

```bash
journalctl -u second-brain -f
```

---

## 7. nginx reverse proxy

```bash
cat > /etc/nginx/sites-available/second-brain <<'EOF'
server {
    listen 80;
    server_name brain.example.com;

    # certbot fills the rest after we run it.

    client_max_body_size 20M;   # voice uploads

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    # WebSocket upgrade for /ws
    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        "upgrade";
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400s;
    }
}
EOF

ln -s /etc/nginx/sites-available/second-brain /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

---

## 8. HTTPS via Let's Encrypt

```bash
certbot --nginx -d brain.example.com \
        --redirect --agree-tos -m you@example.com -n

# Auto-renewal is wired up by the certbot package via a systemd timer.
systemctl status certbot.timer
```

Now `https://brain.example.com` works, HTTP redirects to HTTPS,
and `X-Forwarded-Proto: https` flows to uvicorn — the session cookie
will carry the `Secure` flag.

---

## 9. Smoke test

Open the site in a browser. You should see the browser's Basic Auth
prompt; enter username/password from `.env`. After login the graph loads
and the WebSocket upgrades (DevTools → Network → WS → status 101).

```bash
# From any machine:
curl -i -u maksim:'your-strong-password' https://brain.example.com/api/graph
# Expect 200 + JSON
curl -i https://brain.example.com/api/graph
# Expect 401 + WWW-Authenticate: Basic
```

---

## 10. Updating

```bash
ssh root@<server>
sudo -u brain bash -c 'cd /opt/second-brain && git pull'
# Reinstall deps only when requirements.txt changes:
sudo -u brain /opt/second-brain/venv/bin/pip install -r /opt/second-brain/requirements.txt
systemctl restart second-brain
```

The in-memory session store clears on every restart, so all logged-in
sessions need to re-auth via Basic the next time they hit the site —
expected for a single-user app.

---

## 11. Backups (recommended)

`brain.json` is your entire data. Back it up:

```bash
cat > /etc/cron.daily/brain-backup <<'EOF'
#!/bin/bash
set -e
TS=$(date +%Y%m%d-%H%M%S)
DEST=/var/backups/brain
mkdir -p "$DEST"
cp /opt/second-brain/data/brain.json "$DEST/brain-$TS.json"
# keep last 30 days
find "$DEST" -name 'brain-*.json' -mtime +30 -delete
EOF
chmod +x /etc/cron.daily/brain-backup
```

Optionally push backups off-box (rsync to another VPS, S3, etc.).

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `502 Bad Gateway` | uvicorn not running — `systemctl status second-brain`, check `journalctl` |
| Browser prompts for password every request | Cookie blocked. Make sure HTTPS is live so `Secure` cookie isn't dropped, and `X-Forwarded-Proto` reaches uvicorn (`FORWARDED_ALLOW_IPS=127.0.0.1` set) |
| `400 Invalid host header` | `ALLOWED_HOSTS` doesn't include your domain |
| WebSocket disconnects with code 1008 | No `session_token` cookie — Basic-auth a regular endpoint first to mint one |
| `503` from `/api/voice` | `OPENAI_API_KEY` not set and `faster-whisper` not installed |
| `502` from `/api/thoughts` or `/api/coach` | `ANTHROPIC_API_KEY` missing or wrong; check logs |
