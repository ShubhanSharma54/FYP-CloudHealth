#!/bin/bash
# ONE COMMAND TO RUN EVERYTHING
# Copy this entire line and paste into your EC2 terminal:

python3 -c "
import os,time,requests,sys
from datetime import datetime
try:import psutil
except:
 import subprocess;subprocess.check_call([sys.executable,'-m','pip','install','psutil','requests']);import psutil
BACKEND_URL=os.getenv('BACKEND_URL','http://localhost:8000')
INSTANCE_ID='i-07aafc7c37daf9563'
print(f'Agent starting... Backend:{BACKEND_URL}')
while True:
 m={'instance_id':INSTANCE_ID,'cpu':round(psutil.cpu_percent(interval=1),1),'memory':round(psutil.virtual_memory().percent,1),'disk':round(psutil.disk_usage('/').percent,1),'network_in':0,'network_out':0,'disk_io':0,'uptime_seconds':0,'timestamp':datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
 try:
  r=requests.post(f'{BACKEND_URL}/api/local-metrics',json=m,timeout=10)
  print(f'[OK] CPU:{m[\"cpu\"]}% Mem:{m[\"memory\"]}%'if r.status_code==200else f'[FAIL]{r.status_code}')
 except Exception as e:print(f'[ERR]{e}')
 time.sleep(60)
"