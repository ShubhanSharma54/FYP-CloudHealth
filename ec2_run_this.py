#!/usr/bin/env python3
# CloudHealth Agent - Simple One-File Version
# Copy ALL of this and paste into your EC2 terminal

import os, time, requests, socket
from datetime import datetime

try:
    import psutil
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'psutil', 'requests'])
    import psutil

BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:8000')
INSTANCE_ID = 'i-07aafc7c37daf9563'

def get_metrics():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net = psutil.net_io_counters()
    return {
        'instance_id': INSTANCE_ID,
        'cpu': round(psutil.cpu_percent(interval=1), 1),
        'memory': round(mem.percent, 1),
        'disk': round(disk.percent, 1),
        'network_in': net.bytes_recv,
        'network_out': net.bytes_sent,
        'disk_io': 0,
        'uptime_seconds': 0,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

def main():
    print(f"CloudHealth Agent starting...")
    print(f"Backend: {BACKEND_URL}")
    print(f"Instance: {INSTANCE_ID}")
    print("-" * 40)
    
    while True:
        try:
            m = get_metrics()
            r = requests.post(f"{BACKEND_URL}/api/local-metrics", json=m, timeout=10)
            if r.status_code == 200:
                print(f"[OK] CPU:{m['cpu']}% Mem:{m['memory']}% Disk:{m['disk']}%")
            else:
                print(f"[FAIL] Status: {r.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"[ERROR] Cannot connect to {BACKEND_URL}")
        except Exception as e:
            print(f"[ERROR] {e}")
        time.sleep(60)

if __name__ == '__main__':
    main()