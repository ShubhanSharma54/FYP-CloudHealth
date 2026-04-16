#!/bin/bash
# CloudHealth AWS Integration Test Script
# Run this on your EC2 instance to test AWS connectivity

echo "=========================================="
echo "CloudHealth AWS Integration Test"
echo "=========================================="

cd /home/kingMuhamed/CloudHealth/backend

echo ""
echo "1. Testing AWS Credentials..."
python3 -c "
from aws_metrics import check_aws_credentials
result = check_aws_credentials()
print(f'   AWS Available: {result}')
"

echo ""
echo "2. Testing EC2 Instance Discovery..."
python3 -c "
from aws_metrics import get_ec2_instances
instances = get_ec2_instances()
print(f'   Found {len(instances)} EC2 instances')
for inst in instances:
    print(f'   - {inst[\"name\"]} ({inst[\"id\"]}) - {inst[\"type\"]} - {inst[\"state\"]}')
"

echo ""
echo "3. Testing Metrics Fetch..."
python3 -c "
from aws_metrics import fetch_ec2_metrics, TARGET_INSTANCE_ID
print(f'   Fetching metrics for: {TARGET_INSTANCE_ID}')
metrics = fetch_ec2_metrics(TARGET_INSTANCE_ID, 1)
print(f'   CPU data points: {len(metrics.get(\"cpu_utilization\", []))}')
print(f'   Memory data points: {len(metrics.get(\"memory_usage\", []))}')
print(f'   Current CPU: {metrics.get(\"current_cpu\", \"N/A\")}')
print(f'   Current Memory: {metrics.get(\"current_memory\", \"N/A\")}')
print(f'   Disk Usage: {metrics.get(\"disk_usage\", \"N/A\")}%')
"

echo ""
echo "=========================================="
echo "Test Complete!"
echo "=========================================="
echo ""
echo "To start the CloudHealth server:"
echo "   python3 -m uvicorn main:app --host 0.0.0.0 --port 8000"
echo ""
echo "Then access the dashboard at:"
echo "   http://<your-ec2-public-ip>:8000"