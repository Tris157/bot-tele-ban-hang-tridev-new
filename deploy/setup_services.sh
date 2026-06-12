#!/bin/bash
# ===================================================
# Deploy script for Telegram Shop Bot
# Run on VPS: bash deploy/setup_services.sh
# ===================================================

set -e
echo "=== Setting up systemd services ==="

# 1. Stop old processes
echo "[1/6] Stopping old processes..."
pkill -f "python -m app.main" 2>/dev/null || true
pkill -f "cloudflared tunnel run" 2>/dev/null || true
sleep 2

# 2. Install shopbot service
echo "[2/6] Installing shopbot.service..."
cat > /etc/systemd/system/shopbot.service << 'EOF'
[Unit]
Description=Telegram Shop Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/bot-tele-ban-hang-tridev-new
ExecStart=/root/bot-tele-ban-hang-tridev-new/venv/bin/python -m app.main
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 3. Install cloudflared service
echo "[3/6] Installing cloudflared.service..."
cat > /etc/systemd/system/cloudflared-tunnel.service << 'EOF'
[Unit]
Description=Cloudflare Tunnel for bot.doantri.dev
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/cloudflared tunnel run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 4. Enable and start services
echo "[4/6] Enabling services to start on boot..."
systemctl daemon-reload
systemctl enable shopbot.service
systemctl enable cloudflared-tunnel.service

echo "[5/6] Starting services..."
systemctl start cloudflared-tunnel.service
sleep 2
systemctl start shopbot.service
sleep 3

# 5. Show status
echo "[6/6] Checking status..."
echo ""
echo "=== shopbot.service ==="
systemctl status shopbot.service --no-pager -l | head -15
echo ""
echo "=== cloudflared-tunnel.service ==="
systemctl status cloudflared-tunnel.service --no-pager -l | head -15

echo ""
echo "=== DONE! Both services will auto-start on VPS reboot ==="
echo ""
echo "Useful commands:"
echo "  systemctl status shopbot              # Check bot status"
echo "  systemctl restart shopbot             # Restart bot"
echo "  journalctl -u shopbot -f              # Follow bot logs"
echo "  systemctl status cloudflared-tunnel   # Check tunnel status"
echo "  journalctl -u cloudflared-tunnel -f   # Follow tunnel logs"
