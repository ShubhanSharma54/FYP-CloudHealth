#!/bin/bash
# CloudHealth Local Metrics Agent - Deployment Script
# Run this on your EC2 instance to set up metric collection
# Usage: chmod +x deploy_agent.sh && ./deploy_agent.sh

set -e

echo "=========================================="
echo "CloudHealth Local Metrics Agent Deployer"
echo "=========================================="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_SCRIPT="$SCRIPT_DIR/local_metrics_agent.py"

if [ ! -f "$AGENT_SCRIPT" ]; then
    echo "ERROR: local_metrics_agent.py not found in $SCRIPT_DIR"
    exit 1
fi

echo ""
echo "Step 1: Installing Python dependencies..."
if command -v pip3 &> /dev/null; then
    pip3 install psutil requests --quiet
    echo "  ✓ Dependencies installed"
elif command -v pip &> /dev/null; then
    pip install psutil requests --quiet
    echo "  ✓ Dependencies installed"
else
    echo "ERROR: pip not found. Please install pip first."
    exit 1
fi

echo ""
echo "Step 2: Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "  Using Python $PYTHON_VERSION"

echo ""
echo "Step 3: Testing metric collection..."
python3 "$AGENT_SCRIPT" --test
echo "  ✓ Metric collection works"

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "To start the agent, you have options:"
echo ""
echo "Option 1: Manual run (for testing)"
echo "  INSTANCE_ID=i-07aafc7c37daf9563 BACKEND_URL=http://YOUR_SERVER_IP:8000 python3 local_metrics_agent.py"
echo ""
echo "Option 2: Run as background service"
echo "  nohup INSTANCE_ID=i-07aafc7c37daf9563 BACKEND_URL=http://YOUR_SERVER_IP:8000 python3 local_metrics_agent.py --daemon > agent.log 2>&1 &"
echo ""
echo "Option 3: Systemd service (recommended for production)"
echo "  See: https://cloudhealth-local-agent.example.com/systemd"
echo ""
echo "To check if agent is running:"
echo "  ps aux | grep local_metrics_agent"
echo ""
echo "To view logs:"
echo "  tail -f agent.log"
echo ""
echo "=========================================="
echo "IMPORTANT: Configure these environment variables:"
echo "  INSTANCE_ID      = Your EC2 instance ID (i-07aafc7c37daf9563)"
echo "  BACKEND_URL     = Your backend server URL (http://YOUR_IP:8000)"
echo "  METRICS_INTERVAL = Seconds between metrics (default: 60)"
echo "=========================================="