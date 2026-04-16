#!/bin/bash
# CloudHealth EC2 Setup Script
# Run this on your AWS Academy Learner Lab EC2 instance

set -e

echo "=========================================="
echo "CloudHealth EC2 Monitoring Setup"
echo "=========================================="

# Check if running on EC2
echo ""
echo "[1/6] Checking EC2 metadata service..."
if curl -s --connect-timeout 3 http://169.254.169.254/latest/meta-data/instance-id > /dev/null 2>&1; then
    echo "✓ Running on EC2 - Instance ID: $(curl -s http://169.254.169.254/latest/meta-data/instance-id)"
else
    echo "⚠ Not running on EC2 or metadata service not available"
    echo "  This script must run on an EC2 instance with IAM role"
fi

# Check AWS credentials
echo ""
echo "[2/6] Checking IAM role..."
if aws sts get-caller-identity > /dev/null 2>&1; then
    echo "✓ AWS credentials available"
    aws sts get-caller-identity | grep Arn
else
    echo "⚠ No AWS credentials found"
    echo "  Ensure EC2 has an IAM role attached (LabInstanceProfile)"
fi

# Install Python dependencies
echo ""
echo "[3/6] Installing Python packages..."
pip3 install --break-system-packages flask boto3 psutil 2>/dev/null || pip3 install flask boto3 psutil

# Create setup script
echo ""
echo "[4/6] Setting up monitoring server..."

# Make script executable
chmod +x cloudwatch_server.py

# Test the server briefly
echo ""
echo "[5/6] Testing server startup..."
timeout 5 python3 cloudwatch_server.py 2>&1 | head -15 || true

echo ""
echo "[6/6] Setup complete!"
echo ""
echo "=========================================="
echo "TO START THE SERVER:"
echo "=========================================="
echo ""
echo "  python3 cloudwatch_server.py"
echo ""
echo "The server will start on:"
echo "  - http://0.0.0.0:5000"
echo ""
echo "API Endpoints:"
echo "  - http://<EC2_IP>:5000/api/status   - Server status"
echo "  - http://<EC2_IP>:5000/api/cpu     - CPU metrics"
echo "  - http://<EC2_IP>:5000/api/memory  - Memory metrics"
echo "  - http://<EC2_IP>:5000/api/network - Network metrics"
echo "  - http://<EC2_IP>:5000/api/disk    - Disk metrics"
echo "  - http://<EC2_IP>:5000/api/all     - All metrics"
echo ""
echo "IMPORTANT: Open port 5000 in your EC2 Security Group!"
echo ""
echo "=========================================="