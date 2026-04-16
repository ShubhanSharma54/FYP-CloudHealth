# CloudHealth Local Metrics Setup Guide

> **For AWS Academy Learner Lab Users**
>
> Since AWS Academy Learner Lab restricts IAM role creation and modifications, this guide uses the Local Metrics Agent approach, which is simpler and more reliable for your environment.

## Overview

The **Local Metrics Agent** collects real system metrics directly from EC2 instances using `psutil` and sends them to your CloudHealth backend. This bypasses any AWS IAM limitations.

### Supported Metrics

The agent collects comprehensive metrics:

- **CPU**: Utilization %, per-core performance, physical/logical cores
- **Memory**: Usage %, used/available/total in MB, swap memory stats
- **Disk**: Usage %, used/free/total space, read/write operations
- **Network**: Throughput in MB/s, packet counts, error statistics
- **System**: Uptime, running processes, hostname
- **Timestamps**: All metrics include precise timestamp for historical tracking

## Prerequisites

1. **EC2 Instance** running Amazon Linux, Ubuntu, or compatible OS
2. **Python 3.6+** installed
3. **SSH Access** to EC2 instance
4. **Backend Server** running and accessible from EC2 instance

## Step-by-Step Setup

### 1. Deploy Backend Server on the same EC2 instance

First, ensure your CloudHealth backend is running:

```bash
# On the same EC2 instance
cd /path/to/CloudHealth/backend

# Install dependencies
pip install -r requirements.txt

# Run the backend server
python main.py
# Backend listens on 0.0.0.0:8000
```

The backend should show: `Running on http://0.0.0.0:8000`

### 2. Connect to EC2 Instance via SSH

```bash
# From your local machine or jump host
ssh -i your-key.pem ec2-user@your-instance-public-ip
# Or for Ubuntu:
ssh -i your-key.pem ubuntu@your-instance-public-ip
```

### 3. Install Dependencies on EC2

```bash
# Update package manager
sudo yum update -y  # For Amazon Linux
# OR
sudo apt update && sudo apt upgrade -y  # For Ubuntu

# Install Python and pip
sudo yum install -y python3 python3-pip  # Amazon Linux
# OR
sudo apt install -y python3 python3-pip  # Ubuntu

# Install required Python packages
pip3 install psutil requests
```

Verify installation:
```bash
python3 -c "import psutil; print('psutil installed successfully')"
```

### 4. Copy Local Metrics Agent to EC2

**Option A: Copy via SCP**
```bash
# From your local machine
scp -i your-key.pem local_metrics_agent.py ec2-user@your-instance-public-ip:~/

# SSH to instance and verify
ssh -i your-key.pem ec2-user@your-instance-public-ip
ls -la local_metrics_agent.py
```

**Option B: Create on EC2 directly**
```bash
# SSH to instance
ssh -i your-key.pem ec2-user@your-instance-public-ip

# Create the file
nano local_metrics_agent.py
# Paste the contents of local_metrics_agent.py from your backend folder
# Press Ctrl+X, then Y, then Enter to save
```

### 5. Configure Environment Variables (localhost topology)

Set the backend URL and instance ID:

```bash
# Get your EC2 instance ID
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
echo "Instance ID: $INSTANCE_ID"

BACKEND_URL="http://localhost:8000"

# Test connectivity to backend
curl -I $BACKEND_URL/api/servers
```

### 6. Test the Agent

```bash
# Make the script executable
chmod +x local_metrics_agent.py

# Run in test mode to verify metrics collection
python3 local_metrics_agent.py --test

# Output should show JSON with current metrics:
# {
#   "instance_id": "i-0123456789abcdef0",
#   "cpu": 25.3,
#   "cpu_cores": {"physical_cores": 2, "logical_cores": 2, "per_core": [20.1, 30.5]},
#   "memory": {"percent": 45.2, "used_mb": 920, "available_mb": 1080, "total_mb": 2000},
#   ...
# }
```

### 7. Run Metrics Agent

**Option A: Manual Testing (Foreground)**
```bash
# Run the agent and send metrics every 60 seconds
python3 local_metrics_agent.py

# Should output:
# 2024-01-15 10:23:45 - INFO - Starting CloudHealth Local Metrics Agent
# 2024-01-15 10:23:45 - INFO -   Instance ID: i-0123456789abcdef0
# 2024-01-15 10:23:45 - INFO -   Backend URL: http://localhost:8000
# 2024-01-15 10:23:45 - INFO -   Interval: 60 seconds
# 2024-01-15 10:23:47 - INFO - Metrics sent successfully - CPU: 25.3%, Memory: 45.2%
```

Stop with `Ctrl+C`

**Option B: With Custom Settings**
```bash
# Override settings via environment variables
BACKEND_URL="http://localhost:8000" \
TARGET_INSTANCE_ID="i-0123456789abcdef0" \
METRICS_INTERVAL="30" \
python3 local_metrics_agent.py
```

### 8. Setup as Systemd Service (Recommended for Production)

Create a systemd service file to run the agent automatically:

```bash
# Create service file
sudo nano /etc/systemd/system/cloudhealth-metrics.service
```

Copy and paste this content:

```ini
[Unit]
Description=CloudHealth Local Metrics Agent
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user
Environment="BACKEND_URL=http://localhost:8000"
Environment="TARGET_INSTANCE_ID=i-0123456789abcdef0"
Environment="METRICS_INTERVAL=60"
ExecStart=/usr/bin/python3 /home/ec2-user/local_metrics_agent.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Important**: Update the following in the service file:
- `BACKEND_URL`: Your backend server IP/hostname and port
- `TARGET_INSTANCE_ID`: Your EC2 instance ID (or let it auto-detect)
- `WorkingDirectory`: Path where local_metrics_agent.py is stored

Then enable and start the service:

```bash
# Reload systemd daemon
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable cloudhealth-metrics

# Start the service
sudo systemctl start cloudhealth-metrics

# Check status
sudo systemctl status cloudhealth-metrics

# View logs
sudo journalctl -u cloudhealth-metrics -f
```

### 9. Verify Metrics are Being Received

On your backend server, check if metrics are being stored:

```bash
# Query the database
cd /path/to/CloudHealth/backend

python3 << 'EOF'
from database import get_db_connection

conn = get_db_connection()
cursor = conn.cursor()

# Check servers
cursor.execute("SELECT * FROM servers")
servers = cursor.fetchall()
print("Servers:", len(list(servers)))

# Check detailed metrics (recent 5)
cursor.execute("SELECT hostname, cpu_percent, memory_percent, disk_percent, timestamp FROM detailed_metrics ORDER BY timestamp DESC LIMIT 5")
metrics = cursor.fetchall()
for metric in metrics:
    print(f"{metric[0]}: CPU={metric[1]}%, MEM={metric[2]}%, DISK={metric[3]}%, Time={metric[4]}")

conn.close()
EOF
```

### 10. Check Frontend Dashboard

Navigate to your CloudHealth frontend dashboard:
- URL: `http://localhost:8000`
- Metrics should now show real values instead of mock data
- Select the instance from the server dropdown to see its metrics

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_URL` | `http://localhost:8000` | Backend API URL (must be reachable from EC2) |
| `TARGET_INSTANCE_ID` | Auto-detected | EC2 instance ID (auto-fetches from metadata if not set) |
| `METRICS_INTERVAL` | `60` | Seconds between metric collection |
| `API_KEY` | (empty) | Optional API key for authentication |

## Troubleshooting

### Metrics Not Arriving at Backend

1. **Check EC2 to Backend connectivity**:
   ```bash
   # From EC2 instance
   curl -I http://localhost:8000/api/servers
   # Should return HTTP 200
   ```

2. **Check agent is running**:
   ```bash
   ps aux | grep local_metrics_agent.py
   ```

3. **View agent logs**:
   ```bash
   sudo journalctl -u cloudhealth-metrics -f
   ```

4. **Verify instance ID**:
   ```bash
   curl http://169.254.169.254/latest/meta-data/instance-id
   ```

### High CPU/Memory Usage from Agent

The agent is lightweight (~2% CPU), if using more:
- Increase `METRICS_INTERVAL` to 120 or 300 seconds
- Check if backend connection has issues (agent will retry)

### Permission Denied Error

Make sure script is executable and run with proper user:
```bash
chmod +x local_metrics_agent.py
sudo chown ec2-user:ec2-user local_metrics_agent.py
```

## Multiple EC2 Instances

To monitor multiple EC2 instances:

1. Deploy the agent on each instance with unique configuration
2. Each instance auto-creates its own server entry in the database
3. Frontend will show all instances in the server dropdown

```bash
# Instance 1
BACKEND_URL="http://localhost:8000" python3 local_metrics_agent.py

# Instance 2
BACKEND_URL="http://localhost:8000" python3 local_metrics_agent.py
# Auto-detects different instance ID automatically
```

## Performance Notes

- **Agent Overhead**: ~2-5% CPU, 20-30 MB RAM
- **Network**: ~5-10 KB per metric collection (every 60s by default)
- **Database**: ~1-2 MB per day per instance
- **Retention**: Metrics stored indefinitely (consider archiving for long-term)

## Security Considerations

🔒 **For Production**:
1. For same-instance deployment, use localhost: `http://localhost:8000`
2. Add API key authentication: Set `API_KEY` environment variable
3. Restrict backend network access using Security Groups
4. Store credentials in AWS Secrets Manager or Parameter Store
5. Rotate credentials regularly

## Next Steps

1. ✅ Deploy agent on all EC2 instances
2. ✅ Verify metrics arriving in dashboard
3. ✅ Configure alerts based on thresholds
4. ✅ Set up log rotation for database
5. ✅ Create backup strategy for metrics database

---

**Need Help?**
- Check backend logs: `tail -f /var/log/cloudhealth.log`
- Review agent logs: `sudo journalctl -u cloudhealth-metrics`
- Database queries: See database.py for schema
