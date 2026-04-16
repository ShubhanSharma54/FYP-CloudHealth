#!/bin/bash

# CloudHealth Metrics Agent Setup Script for EC2
# Automates installation and configuration of the local metrics agent
# Usage: bash setup_metrics_agent.sh [BACKEND_URL] [INSTANCE_ID] [INTERVAL]

set -e  # Exit on error

BACKEND_URL="${1:-http://localhost:8000}"
INSTANCE_ID="${2:-}"  # Empty = auto-detect
METRICS_INTERVAL="${3:-60}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "CloudHealth Local Metrics Agent Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Configuration:"
echo "  Backend URL: $BACKEND_URL"
echo "  Instance ID: ${INSTANCE_ID:-auto-detect}"
echo "  Interval: ${METRICS_INTERVAL}s"
echo ""

# Detect OS
if grep -q "Amazon Linux\|CentOS\|RHEL" /etc/os-release; then
    OS="amazon"
    PKG_MANAGER="yum"
    PYTHON_CMD="python3"
elif grep -q "Ubuntu\|Debian" /etc/os-release; then
    OS="ubuntu"
    PKG_MANAGER="apt"
    PYTHON_CMD="python3"
else
    echo "❌ Unsupported OS"
    exit 1
fi

echo "✓ Detected OS: $OS"
echo ""

# Step 1: Update system
echo "Step 1: Updating system packages..."
if [ "$OS" = "amazon" ]; then
    sudo yum update -y > /dev/null 2>&1
else
    sudo apt update > /dev/null 2>&1
fi
echo "✓ System packages updated"
echo ""

# Step 2: Install Python and pip
echo "Step 2: Installing Python and pip..."
if [ "$OS" = "amazon" ]; then
    sudo yum install -y python3 python3-pip > /dev/null 2>&1
else
    sudo apt install -y python3 python3-pip > /dev/null 2>&1
fi
echo "✓ Python installation complete"
echo ""

# Step 3: Install required packages
echo "Step 3: Installing Python dependencies..."
pip3 install -q psutil requests
echo "✓ Dependencies installed"
echo ""

# Step 4: Download or create metrics agent
echo "Step 4: Setting up metrics agent script..."
if [ -f "/tmp/local_metrics_agent.py" ]; then
    cp /tmp/local_metrics_agent.py ~/local_metrics_agent.py
    echo "✓ Copied local_metrics_agent.py"
else
    echo "⚠ local_metrics_agent.py not found in /tmp"
    echo "  Please copy it manually: scp local_metrics_agent.py ec2-user@your-ip:~/"
fi
chmod +x ~/local_metrics_agent.py
echo ""

# Step 5: Test metrics collection
echo "Step 5: Testing metrics collection..."
echo "This will take a few seconds..."
timeout 5 $PYTHON_CMD ~/local_metrics_agent.py --test 2>/dev/null || true
echo "✓ Metrics test complete"
echo ""

# Step 6: Test backend connectivity
echo "Step 6: Testing backend connectivity..."
if curl -s -I "$BACKEND_URL/api/servers" > /dev/null; then
    echo "✓ Backend is reachable at $BACKEND_URL"
else
    echo "⚠ Warning: Backend may not be reachable at $BACKEND_URL"
    echo "  Please verify the URL and try again manually"
fi
echo ""

# Step 7: Setup systemd service
echo "Step 7: Setting up systemd service..."

# Create service file
sudo tee /etc/systemd/system/cloudhealth-metrics.service > /dev/null << EOF
[Unit]
Description=CloudHealth Local Metrics Agent
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$(pwd)
Environment="BACKEND_URL=$BACKEND_URL"
Environment="TARGET_INSTANCE_ID=$INSTANCE_ID"
Environment="METRICS_INTERVAL=$METRICS_INTERVAL"
ExecStart=/usr/bin/python3 $(pwd)/local_metrics_agent.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
echo "✓ Systemd service created"
echo ""

# Step 8: Enable and start service
echo "Step 8: Starting metrics agent service..."
sudo systemctl enable cloudhealth-metrics
sudo systemctl start cloudhealth-metrics

# Wait for service to start
sleep 2

if sudo systemctl is-active --quiet cloudhealth-metrics; then
    echo "✓ Metrics agent is running"
else
    echo "❌ Failed to start metrics agent"
    echo "Run: sudo systemctl status cloudhealth-metrics"
    exit 1
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ CloudHealth Metrics Agent Setup Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next Steps:"
echo "  1. View service status:"
echo "     sudo systemctl status cloudhealth-metrics"
echo ""
echo "  2. View live logs:"
echo "     sudo journalctl -u cloudhealth-metrics -f"
echo ""
echo "  3. Check metrics in dashboard:"
echo "     Visit: $BACKEND_URL"
echo ""
echo "Configuration Details:"
echo "  Service file: /etc/systemd/system/cloudhealth-metrics.service"
echo "  Agent script: $(pwd)/local_metrics_agent.py"
echo "  Background: systemd managed (auto-restart on failure)"
echo ""
echo "To modify settings, edit:"
echo "  sudo nano /etc/systemd/system/cloudhealth-metrics.service"
echo "  sudo systemctl daemon-reload && sudo systemctl restart cloudhealth-metrics"
echo ""
