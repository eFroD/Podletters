# Bare-Metal Deployment with systemd

Alternative to Docker Compose. Requires Redis, MinIO, and Ollama already
running on the host (installed separately).

## Setup

```bash
# Create user
sudo useradd -r -s /usr/sbin/nologin -d /opt/podletters podletters

# Clone repo and install
sudo mkdir -p /opt/podletters
sudo cp -r . /opt/podletters/
cd /opt/podletters
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env  # edit with real values

# Install unit files
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now podletters-worker podletters-api
```

## Commands

```bash
sudo systemctl status podletters-worker
sudo systemctl status podletters-api
sudo journalctl -u podletters-worker -f   # tail worker logs
sudo journalctl -u podletters-api -f      # tail API logs
```
