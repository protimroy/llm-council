# Deploying LLM Council to a VPC Without Docker

The simplest no-Docker deployment is a small Linux VM in your VPC running two `systemd` services:

- `llm-council-backend.service` for FastAPI on port `8001`
- `llm-council-frontend.service` for the built static frontend on port `5173`

For public traffic, put Caddy, Nginx, or your cloud load balancer in front of those ports and terminate TLS there.

## 1. Provision a VM

Use Ubuntu 22.04/24.04 or Debian 12 with private networking enabled. Open only the ports you need in the security group/firewall:

- SSH from your admin IP
- HTTP/HTTPS from your load balancer or public clients
- Backend/frontend ports only from trusted internal sources if you do not proxy them

## 2. Install runtime dependencies

```bash
sudo apt update
sudo apt install -y git curl python3 python3-venv nodejs npm
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo install -m 755 ~/.local/bin/uv /usr/local/bin/uv
```

Use Node.js `20.19+` or `22.12+` for Vite 7. If your distro package is older, install Node from NodeSource, fnm, or nvm before building the frontend.

## 3. Create a service user and deploy the repo

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin llm-council
sudo mkdir -p /opt/llm-council
sudo chown llm-council:llm-council /opt/llm-council
sudo -u llm-council git clone <your-repo-url> /opt/llm-council
cd /opt/llm-council
```

## 4. Configure `.env`

Copy `.env.example` to `.env`, then set production values:

```bash
sudo -u llm-council cp .env.example .env
sudo -u llm-council nano .env
```

Important production values:

```bash
OPENROUTER_API_KEY=sk-or-v1-your-real-key
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8001
FRONTEND_HOST=0.0.0.0
FRONTEND_PORT=5173
VITE_API_BASE=https://your-domain.example
CORS_ORIGINS=https://your-domain.example
```

If you serve the frontend and backend on different hostnames, set `VITE_API_BASE` to the backend URL and include the frontend URL in `CORS_ORIGINS`.

## 5. Install and build

```bash
sudo -u llm-council uv sync
sudo -u llm-council bash -lc 'cd frontend && npm ci && npm run build'
```

## 6. Install systemd services

Service templates are provided in `deploy/systemd/` and assume the repo lives at `/opt/llm-council`.

```bash
sudo cp deploy/systemd/llm-council-backend.service /etc/systemd/system/
sudo cp deploy/systemd/llm-council-frontend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now llm-council-backend llm-council-frontend
```

Check status and logs:

```bash
sudo systemctl status llm-council-backend llm-council-frontend
sudo journalctl -u llm-council-backend -f
sudo journalctl -u llm-council-frontend -f
```

Both services use `Restart=always`, so systemd restarts them after crashes and after VM reboot.

## 7. Put a reverse proxy in front

For the easiest TLS setup, use Caddy or your cloud load balancer. A minimal Caddyfile can proxy one public domain to the frontend and API:

```caddyfile
your-domain.example {
  handle /api/* {
    reverse_proxy 127.0.0.1:8001
  }

  handle {
    reverse_proxy 127.0.0.1:5173
  }
}
```

With Nginx, serve `frontend/dist` directly and proxy `/api/` to `127.0.0.1:8001`.

## 8. Updating the deployment

```bash
cd /opt/llm-council
sudo -u llm-council git pull
sudo -u llm-council uv sync
sudo -u llm-council bash -lc 'cd frontend && npm ci && npm run build'
sudo systemctl restart llm-council-backend llm-council-frontend
```
