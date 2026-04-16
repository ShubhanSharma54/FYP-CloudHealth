# CloudHealth - EC2 Monitoring for AWS Academy Learner Lab

This guide explains how to run the CloudHealth monitoring system on AWS Academy Learner Lab where IAM access keys are not available.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AWS Academy Learner Lab                 │
│                                                             │
│  ┌──────────────────┐      ┌────────────────────────────┐  │
│  │   EC2 Instance   │      │                            │  │
│  │                  │      │   LabInstanceProfile       │  │
│  │  ┌────────────┐  │      │   (IAM Role)               │  │
│  │  │  Flask     │◄─┼──────┼──────── boto3 uses        │  │
│  │  │  Server    │  │      │    (no keys needed)       │  │
│  │  │  :5000     │  │      │                            │  │
│  │  └────────────┘  │      └────────────────────────────┘  │
│  │        │         │               │                      │
│  │        ▼         │               ▼                      │
│  │  ┌──────────────────────────────────────────────┐       │
│  │  │         AWS CloudWatch                       │       │
│  │  │  - CPUUtilization  (AWS/EC2)                 │       │
│  │  │  - NetworkIn/Out   (AWS/EC2)                  │       │
│  │  │  - mem_used_percent (CWAgent)                │       │
│  │  │  - disk_used_percent (CWAgent)              │       │
│  │  └──────────────────────────────────────────────┘       │
│  └─────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **EC2 Instance** - Running in AWS Academy Learner Lab
2. **IAM Role** - `LabInstanceProfile` attached to the instance (usually pre-configured)
3. **Python 3** - Installed on the EC2 instance
4. **Security Group** - Port 5000 open for incoming traffic

## Quick Start

### 1. Install Dependencies

```bash
# SSH into your EC2 instance, then:

# Install required Python packages
pip3 install --break-system-packages flask boto3 psutil

# Or without --break-system-packages (if using venv)
pip3 install flask boto3 psutil
```

### 2. Start the Server

```bash
cd /home/kingMuhamed/CloudHealth/backend
python3 cloudwatch_server.py
```

The server will start on `http://0.0.0.0:5000`

### 3. Configure Security Group

**IMPORTANT**: You must open port 5000 in your EC2 security group:

1. Go to EC2 Dashboard → Security Groups
2. Select your instance's security group
3. Inbound Rules → Edit → Add Rule:
   - Type: Custom TCP
   - Port: 5000
   - Source: Your IP (or 0.0.0.0/0 for anywhere)

### 4. Get Your EC2 Public IP

```bash
# From your local machine, find the public IP:
# EC2 Console → Instances → Your Instance → Public IPv4 Address

# Or from the EC2 instance itself:
curl -s http://169.254.169.254/latest/meta-data/public-ipv4
```

### 5. Test the API

```bash
# Replace <EC2_IP> with your actual public IP
curl http://<EC2_IP>:5000/api/status
curl http://<EC2_IP>:5000/api/cpu
curl http://<EC2_IP>:5000/api/memory
```

## API Endpoints

| Endpoint | Description | Example Response |
|----------|-------------|------------------|
| `/api/status` | Server health & instance info | `{"status": "running", "instance_id": "i-xxx"}` |
| `/api/cpu` | CPU utilization (%) | `{"current": 45.2, "data": [{"time": "14:00", "value": 45.2}]}` |
| `/api/memory` | Memory utilization (%) | `{"current": 67.8, "data": [...], "source": "psutil"}` |
| `/api/network` | Network I/O (bytes) | `{"network_in": [...], "network_out": [...]}` |
| `/api/disk` | Disk I/O (bytes) | `{"disk_read": [...], "disk_write": [...]}` |
| `/api/all` | All metrics combined | Full dashboard data |

### Example Responses

**CPU:**
```json
{
  "metric": "CPUUtilization",
  "current": 45.2,
  "data": [
    {"time": "14:25", "value": 42.1},
    {"time": "14:26", "value": 45.2}
  ],
  "source": "cloudwatch",
  "instance_id": "i-07aafc7c37daf9563"
}
```

**Memory (with fallback):**
```json
{
  "metric": "MemoryUtilization",
  "current": 67.8,
  "data": [{"time": "14:26", "value": 67.8}],
  "source": "psutil",
  "instance_id": "i-07aafc7c37daf9563",
  "note": "Using local psutil (CloudWatch Agent not installed)"
}
```

## How It Works (No Access Keys!)

### 1. EC2 Instance Metadata
When running on EC2, the instance metadata service provides:
- Instance ID
- IAM role credentials (temporary)
- Public/Private IPs

### 2. Automatic Credential Detection
The code uses boto3's **default credential chain**:

```python
# No access keys needed - boto3 automatically:
# 1. Checks EC2 instance metadata (IAM role)
# 2. Then checks environment variables
# 3. Then checks ~/.aws/credentials

client = boto3.client('cloudwatch', region_name='us-east-1')
```

### 3. CloudWatch Metrics Fetched

| Metric | Namespace | Description |
|--------|-----------|-------------|
| CPUUtilization | AWS/EC2 | CPU percentage |
| NetworkIn | AWS/EC2 | Bytes received |
| NetworkOut | AWS/EC2 | Bytes sent |
| mem_used_percent | CWAgent | Memory % (if agent installed) |
| disk_used_percent | CWAgent | Disk % (if agent installed) |

### 4. Fallback to psutil
If CloudWatch Agent is not installed, the server falls back to local `psutil`:

```python
import psutil
mem = psutil.virtual_memory()
# Returns: mem.percent (e.g., 67.8)
```

## Frontend Integration

### Option 1: Direct API Calls (React)

```javascript
// In your React component
const EC2_IP = '54.123.45.67'; // Your EC2 public IP
const API_BASE = `http://${EC2_IP}:5000`;

async function fetchMetrics() {
  const [cpu, memory, network, disk] = await Promise.all([
    fetch(`${API_BASE}/api/cpu`).then(r => r.json()),
    fetch(`${API_BASE}/api/memory`).then(r => r.json()),
    fetch(`${API_BASE}/api/network`).then(r => r.json()),
    fetch(`${API_BASE}/api/disk`).then(r => r.json()),
  ]);
  
  return { cpu, memory, network, disk };
}

// Usage
const metrics = await fetchMetrics();
console.log(`CPU: ${metrics.cpu.current}%`);
```

### Option 2: Update Existing Backend

The main `main.py` has been updated to automatically detect the EC2 instance ID and use AWS credentials. It will:
1. Get instance ID from EC2 metadata
2. Use IAM role via boto3
3. Fall back to mock data if no credentials

## Troubleshooting

### "Unable to locate credentials"

**Cause**: EC2 instance doesn't have an IAM role attached.

**Solution**: 
- In AWS Academy, ensure your EC2 has the `LabInstanceProfile` role
- This role should have CloudWatch read permissions

### "No CPU metrics available"

**Cause**: CloudWatch might not have data yet (can take 5 minutes).

**Solution**: 
- Wait a few minutes after launching the instance
- Check CloudWatch Console → Metrics → EC2

### "Connection refused" on port 5000

**Cause**: Security group blocking the port.

**Solution**:
- Add inbound rule for TCP port 5000 in your security group

### "Connection timeout" to EC2

**Cause**: EC2 not reachable from your location.

**Solution**:
- Check EC2 is in a public subnet
- Ensure Public IP is assigned
- Check route table has Internet Gateway

## Alternative: Run as Systemd Service

Create `/etc/systemd/system/cloudhealth.service`:

```ini
[Unit]
Description=CloudHealth EC2 Monitoring
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/CloudHealth/backend
ExecStart=/usr/bin/python3 cloudwatch_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable cloudhealth
sudo systemctl start cloudhealth
```

## License

MIT