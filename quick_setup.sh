#!/bin/bash
# CloudHealth Quick Setup - Run this on your EC2 instance
# Just copy and paste ONE command below to get started!

# ONE COMMAND TO RUN EVERYTHING:
# curl -s https://raw.githubusercontent.com/YOUR_GITHUB/cloudhealth/main/backend/quick_setup.sh | bash

# Or run these commands one by one in your EC2 terminal:

echo "=========================================="
echo "CloudHealth Quick Setup"
echo "=========================================="

# Install dependencies
echo "[1/4] Installing Python dependencies..."
pip3 install psutil requests --quiet

# Create the agent script
echo "[2/4] Creating agent script..."
cat > local_metrics_agent.py << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
import os, sys, time, json, logging, socket, requests
from datetime import datetime

try:
    import psutil
except ImportError:
    print("ERROR: Run 'pip3 install psutil requests' first")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:8000')
INSTANCE_ID = os.getenv('INSTANCE_ID', 'i-07aafc7c37daf9563')
INTERVAL = int(os.getenv('INTERVAL', '60'))

class MetricsCollector:
    def __init__(self):
        self.boot_time = psutil.boot_time()
        self.prev_net_io = psutil.net_io_counters()
        self.prev_disk_io = psutil.disk_io_counters()
        self.prev_time = time.time()
    
    def get_all(self):
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        disk_io = psutil.disk_io_counters()
        
        return {
            'instance_id': INSTANCE_ID,
            'cpu': round(cpu, 2),
            'memory': round(mem.percent, 2),
            'disk': round(disk.percent, 2),
            'network_in': net.bytes_recv,
            'network_out': net.bytes_sent,
            'disk_io': disk_io.read_bytes + disk_io.write_bytes,
            'uptime_seconds': int(time.time() - self.boot_time),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

def send_metrics(metrics):
    try:
        r = requests.post(f"{BACKEND_URL}/api/local-metrics", json=metrics, timeout=10)
        if r.status_code == 200:
            logger.info(f"Sent - CPU:{metrics['cpu']}% Mem:{metrics['memory']}% Disk:{metrics['disk']}%")
            return True
    except Exception as e:
        logger.error(f"Error: {e}")
    return False

def main():
    collector = MetricsCollector()
    logger.info(f"Agent starting - Backend: {BACKEND_URL} - Interval: {INTERVAL}s")
    
    while True:
        try:
            send_metrics(collector.get_all())
        except KeyboardInterrupt:
            break
        time.sleep(INTERVAL)

if __name__ == '__main__':
    main()
PYTHON_SCRIPT

echo "[3/4] Making script executable..."
chmod +x local_metrics_agent.py

echo "[4/4] Starting agent..."
echo ""
echo "=========================================="
echo "SETUP COMPLETE!"
echo "=========================================="
echo ""
echo "YOUR BACKEND URL: http://localhost:8000"
echo "(change BACKEND_URL if different)"
echo ""
echo "To start agent, run:"
echo "  BACKEND_URL=http://localhost:8000 python3 local_metrics_agent.py"
echo ""
echo "Or to run in background:"
echo "  nohup BACKEND_URL=http://localhost:8000 python3 local_metrics_agent.py > agent.log 2>&1 &"
echo ""
echo "Agent is ready! Now start your backend server and visit your dashboard."