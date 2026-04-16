# CloudHealth AWS EC2 Metrics Monitoring - Quick Start

## 🚀 For AWS Academy Learner Lab Users

Since AWS Academy has restricted IAM permissions, we're using the **Local Metrics Agent** approach - the most reliable solution for your constraints.

---

## What's New

Your CloudHealth backend now supports:

✅ **Real Metrics Collection** - No more mock data  
✅ **Detailed Metrics** - CPU, RAM, Disk, Network, Uptime, Process count  
✅ **Multiple Instances** - Monitor multiple EC2 instances from one dashboard  
✅ **Automatic Server Registration** - New instances auto-register when agent connects  
✅ **High-Resolution Data** - Metrics collected every 60 seconds (configurable)  

---

## Architecture

```
EC2 Instance                CloudHealth Backend
    │                              │
    ├─ local_metrics_agent.py      │
    │   (collects metrics)         │
    │   every 60s                  │
    │                              │
    └──── HTTP POST ───────────────> /api/local-metrics
         (sends JSON)              │
                                   ├─ Stores in database
                                   ├─ Returns to frontend
                                   └─ Dashboard displays
                                              │
                                         Frontend
                                        (dashboard)
```

---

## Quick Setup (3 Steps)

### Step 1: Start Backend Server (same EC2 instance)

```bash
cd CloudHealth/backend
python main.py
# Backend listens on 0.0.0.0:8000
```

### Step 2: SSH to EC2 Instance

```bash
ssh -i your-key.pem ec2-user@your-instance-ip
# Or Ubuntu:
ssh -i your-key.pem ubuntu@your-instance-ip
```

### Step 3: Run Local Agent on the same EC2

```bash
# Option A: Automated setup (recommended)
cd ~
bash setup_metrics_agent.sh http://localhost:8000

# Option B: Manual setup
# See LOCAL_METRICS_SETUP.md for detailed instructions
```

---

## Verify It's Working

### On EC2 Instance:
```bash
sudo systemctl status cloudhealth-metrics
sudo journalctl -u cloudhealth-metrics -f  # View logs
```

### On Backend Server:
```bash
# Check if metrics are arriving
python3 << 'EOF'
from database import get_db_connection
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute("SELECT hostname, cpu_percent, memory_percent FROM detailed_metrics ORDER BY timestamp DESC LIMIT 1")
print(cursor.fetchone())
conn.close()
EOF
```

### On Dashboard:
- Open: `http://localhost:8000`
- Should show real metrics instead of mock data ✅

---

## Metrics Collected

| Metric | What It Shows | Example |
|--------|---------------|---------|
| **CPU** | CPU utilization % | 45.2% |
| **Memory** | RAM usage % + details | 62.1% (1240/2000 MB) |
| **Disk** | Storage usage % + details | 55.3% (45/82 GB) |
| **Network** | Data rate in MB/s | In: 2.3 MB/s, Out: 1.1 MB/s |
| **Uptime** | System running time | 15 days 3 hours |
| **Processes** | Running processes count | 82 processes |

---

## Configuration

**Backend URL**: Where metrics are sent to
```bash
BACKEND_URL=http://localhost:8000
```

**Collection Interval**: How often metrics are collected
```bash
METRICS_INTERVAL=60  # Seconds (default: 60, adjust to 30-300)
```

**Edit Service**:
```bash
sudo nano /etc/systemd/system/cloudhealth-metrics.service
sudo systemctl daemon-reload
sudo systemctl restart cloudhealth-metrics
```

---

## Monitoring Multiple Instances

Each EC2 instance that runs the agent sends metrics independently:

```bash
# Instance 1
BACKEND_URL=http://localhost:8000 python3 local_metrics_agent.py

# Instance 2
BACKEND_URL=http://localhost:8000 python3 local_metrics_agent.py
# Each auto-detects its instance ID

# Dashboard shows all instances in dropdown
```

---

## Database Tables

The backend now uses these tables for metrics:

| Table | Purpose |
|-------|---------|
| `servers` | EC2 instance info (id, name, instance_id, status) |
| `metrics` | Simple metrics (latest CPU, RAM, Disk %) |
| `detailed_metrics` | Rich metrics (all fields: cores, usage, IO, network errors) |
| `alerts` | Alert history |
| `logs` | Action logs |

---

## Troubleshooting

### Metrics not arriving?

1. **Test connectivity**:
   ```bash
   curl -I http://localhost:8000/api/servers
   ```

2. **Check agent is running**:
   ```bash
   ps aux | grep local_metrics_agent
   ```

3. **View agent logs**:
   ```bash
   sudo journalctl -u cloudhealth-metrics -n 50 -f
   ```

4. **Test metrics manually**:
   ```bash
   python3 local_metrics_agent.py --test
   ```

### Agent consuming too much CPU?

- Increase interval: `METRICS_INTERVAL=300` (5 minutes)
- Check backend connectivity issues

### Permission errors?

```bash
chmod +x local_metrics_agent.py
sudo chown ec2-user:ec2-user local_metrics_agent.py
```

---

## Files Modified/Created

```
backend/
├── main.py                           (✏️ Updated - added /api/local-metrics endpoint)
├── database.py                       (✏️ Updated - added detailed_metrics table)
├── local_metrics_agent.py            (✏️ Enhanced - better metric collection)
├── LOCAL_METRICS_SETUP.md            (📄 New - comprehensive setup guide)
├── setup_metrics_agent.sh            (📄 New - automated setup script)
├── cloudhealth-metrics.service       (📄 New - systemd service file)
└── AWS_ACADEMY_SETUP.md             (📄 This file)
```

---

## Next Steps

1. ✅ **Deploy Agent** on EC2 instances
2. ✅ **Verify Metrics** arriving in database
3. ✅ Explore dashboard metrics
4. ✅ **Set Thresholds** for alerts (coming soon)
5. ✅ **Add More Instances** as needed

---

## Resources

- **Detailed Setup**: See `LOCAL_METRICS_SETUP.md`
- **Architecture**: See diagrams in setup guide
- **Database Schema**: In `database.py`
- **Frontend Code**: In `frontend/src/pages/Dashboard.jsx`
- **API Endpoints**: Documented in `main.py`

---

## Support

**Check this documentation:**
- `LOCAL_METRICS_SETUP.md` - Comprehensive step-by-step guide
- `backend/main.py` - API endpoint documentation
- `backend/database.py` - Database schema

**Common Issues:**
- Can't reach backend? Check Security Group rules and EC2 network configuration
- Agent not sending? Test with `--test` flag
- Database issues? Verify SQLite permissions in `backend/` directory

---

**Last Updated**: January 2025  
**For**: AWS Academy Learner Lab Users  
**Status**: ✅ Production Ready
