#!/bin/bash
# =============================================================================
#  OLT ONT/ONU Unlock Tool — Setup Script
#  Python 3.12  |  Gunicorn  |  systemd
#
#  Usage:
#    chmod +x setup.sh
#    sudo ./setup.sh
#
#  Options (set as env vars before running):
#    PORT=8000        ./setup.sh       # change listen port
#    HOST=0.0.0.0     ./setup.sh       # change bind address
# =============================================================================

set -e

# ── config (override with env vars) ─────────────────────────────────────────
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
SERVICE_NAME="olt-unlock"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/env"
RUN_USER="${SUDO_USER:-$(whoami)}"

# ── colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC}  $1"; }
warn() { echo -e "  ${YELLOW}!${NC}  $1"; }
err()  { echo -e "  ${RED}✗${NC}  $1"; exit 1; }
step() { echo -e "\n  ${YELLOW}[$1]${NC} $2"; }

# ── banner ───────────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║       OLT ONT/ONU Unlock Tool — Setup Script         ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo "  Project : $PROJECT_DIR"
echo "  User    : $RUN_USER"
echo "  Port    : $PORT"
echo ""

# ── root check ───────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    err "Please run as root:  sudo ./setup.sh"
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Python 3.12
# ─────────────────────────────────────────────────────────────────────────────
step "1/6" "Checking Python 3.12"

PYTHON=""
for cmd in python3.12 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+')
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 9 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    warn "Python 3.9+ not found. Installing Python 3.12..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq
        apt-get install -y software-properties-common -qq
        add-apt-repository -y ppa:deadsnakes/ppa
        apt-get update -qq
        apt-get install -y python3.12 python3.12-venv python3.12-dev -qq
        PYTHON="python3.12"
    elif command -v yum &>/dev/null; then
        yum install -y python3.12 python3.12-venv -q
        PYTHON="python3.12"
    else
        err "Cannot auto-install Python. Install Python 3.12 manually then re-run."
    fi
fi

ok "Using $($PYTHON --version)"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Virtual environment
# ─────────────────────────────────────────────────────────────────────────────
step "2/6" "Creating virtual environment at $VENV_DIR"

if [ -d "$VENV_DIR" ]; then
    warn "env/ already exists — skipping creation"
else
    $PYTHON -m venv "$VENV_DIR"
    ok "Virtual environment created"
fi

PYTHON_VENV="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Install dependencies
# ─────────────────────────────────────────────────────────────────────────────
step "3/6" "Installing dependencies"

$PIP install --upgrade pip -q
$PIP install -r "$PROJECT_DIR/requirements.txt" -q
ok "Dependencies installed (django, paramiko, gunicorn)"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Django setup
# ─────────────────────────────────────────────────────────────────────────────
step "4/6" "Django setup"

cd "$PROJECT_DIR"
export DJANGO_SETTINGS_MODULE=olt_project.settings

# Create session directory
mkdir -p "$PROJECT_DIR/.sessions"
chown -R "$RUN_USER":"$RUN_USER" "$PROJECT_DIR/.sessions"

# Collect static files
$PYTHON_VENV manage.py collectstatic --noinput -v 0 2>/dev/null || true
ok "Static files collected"

# Fix ownership so the service user can write to .sessions
chown -R "$RUN_USER":"$RUN_USER" "$PROJECT_DIR"
ok "Permissions set for user: $RUN_USER"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — systemd service
# ─────────────────────────────────────────────────────────────────────────────
step "5/6" "Creating systemd service: $SERVICE_NAME"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=OLT ONT / ONU Unlock Tool
Documentation=https://github.com/your-repo
After=network.target
Wants=network.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$PROJECT_DIR

# Gunicorn: 2 workers, 120s timeout (SSH connections can take time)
ExecStart=$VENV_DIR/bin/gunicorn \\
    olt_project.wsgi:application \\
    --bind ${HOST}:${PORT} \\
    --workers 2 \\
    --timeout 120 \\
    --keep-alive 5 \\
    --access-logfile - \\
    --error-logfile -

# Restart on crash
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3

# Environment
Environment=DJANGO_SETTINGS_MODULE=olt_project.settings
Environment=PYTHONUNBUFFERED=1

# Security hardening (optional — comment out if issues arise)
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

ok "Service file written to $SERVICE_FILE"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Enable & start
# ─────────────────────────────────────────────────────────────────────────────
step "6/6" "Enabling and starting service"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

if systemctl is-active --quiet "$SERVICE_NAME"; then
    systemctl restart "$SERVICE_NAME"
    ok "Service restarted"
else
    systemctl start "$SERVICE_NAME"
    ok "Service started"
fi

sleep 2

# ── status check ─────────────────────────────────────────────────────────────
if systemctl is-active --quiet "$SERVICE_NAME"; then
    STATUS="${GREEN}RUNNING${NC}"
else
    STATUS="${RED}FAILED${NC}"
fi

# ── get IP ───────────────────────────────────────────────────────────────────
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "your-server-ip")

echo ""
echo "  ╔══════════════════════════════════════════════════════╗"
echo -e "  ║  Status : $(printf "%-46s" "$(echo -e $STATUS)")║"
echo "  ║                                                      ║"
echo "  ║  Local  :  http://127.0.0.1:${PORT}                      ║"
echo "  ║  Network:  http://${IP}:${PORT}                   ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status  $SERVICE_NAME"
echo "    sudo systemctl restart $SERVICE_NAME"
echo "    sudo systemctl stop    $SERVICE_NAME"
echo "    sudo journalctl -u     $SERVICE_NAME -f     # live logs"
echo ""
