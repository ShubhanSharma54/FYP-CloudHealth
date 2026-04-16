# CloudHealth Setup for Kali Linux
# Run these commands one by one in your EC2 terminal:

# Option 1: Use apt (RECOMMENDED)
sudo apt update && sudo apt install -y python3-psutil python3-requests

# If apt doesn't work, use --break-system-packages:
# pip3 install psutil requests --break-system-packages

# Then run agent:
python3 -c "
import os,time,requests
from datetime import datetime
import psutil
BACKEND_URL = 'http://localhost:8000'
INSTANCE_ID = 'i-07aafc7c37daf9563'
while True:
    m = {'instance_id':INSTANCE_ID,'cpu':round(psutil.cpu_percent(interval=1),1),'memory':round(psutil.virtual_memory().percent,1),'disk':round(psutil.disk_usage('/').percent,1),'network_in':0,'network_out':0,'disk_io':0,'uptime_seconds':0,'timestamp':datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    try:
        r = requests.post(f'{BACKEND_URL}/api/local-metrics', json=m, timeout=10)
        print(f'[OK] CPU:{m[\"cpu\"]}% Mem:{m[\"memory\"]}%')
    except Exception as e:
        print(f'[ERR] Cannot connect - is backend running?')
    time.sleep(60)
"