#!/usr/bin/env python3
"""
Local Metrics Agent for CloudHealth
Runs on EC2 instance to collect local system metrics and send to backend API.
Bypasses AWS IAM permissions by collecting metrics locally via psutil.

Usage:
    python local_metrics_agent.py
    
    # Or with custom settings:
    BACKEND_URL=http://your-server:8000 INSTANCE_ID=i-xxxxxxxxxxxxxxxxx python local_metrics_agent.py
"""

import os
import sys
import time
import json
import logging
import socket
import requests
from datetime import datetime
from threading import Thread

try:
    import psutil
except ImportError:
    print("ERROR: psutil not installed. Run: pip install psutil")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:8000')
INSTANCE_ID = os.getenv('TARGET_INSTANCE_ID', os.getenv('INSTANCE_ID', ''))
INTERVAL = int(os.getenv('METRICS_INTERVAL', '60'))
API_KEY = os.getenv('API_KEY', '')

class MetricsCollector:
    def __init__(self):
        self.boot_time = psutil.boot_time()
        self.prev_net_io = psutil.net_io_counters()
        self.prev_disk_io = psutil.disk_io_counters()
        self.prev_time = time.time()
    
    def get_cpu_utilization(self):
        """Get CPU utilization percentage"""
        return round(psutil.cpu_percent(interval=1), 2)
    
    def get_cpu_cores(self):
        """Get CPU core information"""
        return {
            'physical_cores': psutil.cpu_count(logical=False),
            'logical_cores': psutil.cpu_count(logical=True),
            'per_core': psutil.cpu_percent(percpu=True, interval=1)
        }
    
    def get_memory_usage(self):
        """Get memory usage in percentage and bytes"""
        mem = psutil.virtual_memory()
        return {
            'percent': round(mem.percent, 2),
            'used_mb': round(mem.used / (1024 * 1024), 2),
            'available_mb': round(mem.available / (1024 * 1024), 2),
            'total_mb': round(mem.total / (1024 * 1024), 2)
        }
    
    def get_swap_usage(self):
        """Get swap memory usage"""
        swap = psutil.swap_memory()
        return {
            'percent': round(swap.percent, 2),
            'used_mb': round(swap.used / (1024 * 1024), 2),
            'total_mb': round(swap.total / (1024 * 1024), 2)
        }
    
    def get_disk_usage(self, path='/'):
        """Get disk usage for specified path"""
        disk = psutil.disk_usage(path)
        return {
            'percent': round(disk.percent, 2),
            'used_gb': round(disk.used / (1024 * 1024 * 1024), 2),
            'free_gb': round(disk.free / (1024 * 1024 * 1024), 2),
            'total_gb': round(disk.total / (1024 * 1024 * 1024), 2)
        }
    
    def get_disk_io(self):
        """Get disk I/O statistics"""
        try:
            current_disk_io = psutil.disk_io_counters()
            
            read_bytes = current_disk_io.read_bytes - self.prev_disk_io.read_bytes
            write_bytes = current_disk_io.write_bytes - self.prev_disk_io.write_bytes
            read_count = current_disk_io.read_count - self.prev_disk_io.read_count
            write_count = current_disk_io.write_count - self.prev_disk_io.write_count
            
            self.prev_disk_io = current_disk_io
            
            return {
                'read_mb': round(read_bytes / (1024 * 1024), 2),
                'write_mb': round(write_bytes / (1024 * 1024), 2),
                'read_ops': read_count,
                'write_ops': write_count
            }
        except Exception as e:
            logger.error(f"Error getting disk I/O: {e}")
            return {'read_mb': 0, 'write_mb': 0, 'read_ops': 0, 'write_ops': 0}
    
    def get_network_io(self):
        """Get network I/O statistics"""
        try:
            current_net_io = psutil.net_io_counters()
            current_time = time.time()
            
            time_diff = current_time - self.prev_time
            if time_diff == 0:
                time_diff = 1
            
            network_in_mb = (current_net_io.bytes_recv - self.prev_net_io.bytes_recv) / (1024 * 1024) / time_diff
            network_out_mb = (current_net_io.bytes_sent - self.prev_net_io.bytes_sent) / (1024 * 1024) / time_diff
            
            self.prev_net_io = current_net_io
            self.prev_time = current_time
            
            return {
                'in_mb_s': round(network_in_mb, 2),
                'out_mb_s': round(network_out_mb, 2),
                'packets_in': current_net_io.packets_recv,
                'packets_out': current_net_io.packets_sent,
                'errors_in': current_net_io.errin,
                'errors_out': current_net_io.errout,
                'dropped_in': current_net_io.dropin,
                'dropped_out': current_net_io.dropout
            }
        except Exception as e:
            logger.error(f"Error getting network I/O: {e}")
            return {'in_mb_s': 0, 'out_mb_s': 0, 'packets_in': 0, 'packets_out': 0}
    
    def get_uptime_seconds(self):
        """Get system uptime in seconds"""
        return int(time.time() - self.boot_time)
    
    def get_process_info(self):
        """Get information about running processes"""
        try:
            process_count = len(psutil.pids())
            return {
                'total_processes': process_count,
                'running': process_count
            }
        except:
            return {'total_processes': 0, 'running': 0}
    
    def collect(self):
        """Collect all metrics"""
        metrics = {
            'instance_id': INSTANCE_ID,
            'cpu': self.get_cpu_utilization(),
            'cpu_cores': self.get_cpu_cores(),
            'memory': self.get_memory_usage(),
            'swap': self.get_swap_usage(),
            'disk': self.get_disk_usage(),
            'disk_io': self.get_disk_io(),
            'network': self.get_network_io(),
            'processes': self.get_process_info(),
            'uptime_seconds': self.get_uptime_seconds(),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'hostname': socket.gethostname(),
            'source': 'local_agent'
        }
        
        return metrics


def get_instance_id_from_metadata():
    """Try to get instance ID from EC2 metadata service"""
    try:
        import urllib.request
        metadata_url = 'http://169.254.169.254/latest/meta-data/instance-id'
        
        req = urllib.request.Request(metadata_url)
        req.add_header('User-Agent', 'CloudHealth-Agent/1.0')
        
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        logger.debug(f"Could not fetch instance metadata: {e}")
        return None


def send_metrics_to_backend(metrics):
    """Send metrics to CloudHealth backend API"""
    endpoint = f"{BACKEND_URL}/api/local-metrics"
    
    headers = {'Content-Type': 'application/json'}
    if API_KEY:
        headers['X-API-Key'] = API_KEY
    
    try:
        response = requests.post(
            endpoint,
            json=metrics,
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            memory_pct = metrics['memory']['percent'] if isinstance(metrics.get('memory'), dict) else metrics.get('memory', 0)
            logger.info(f"Metrics sent successfully - CPU: {metrics['cpu']}%, Memory: {memory_pct}%")
            return True
        else:
            logger.warning(f"Failed to send metrics: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to backend at {BACKEND_URL}")
        return False
    except Exception as e:
        logger.error(f"Error sending metrics: {e}")
        return False


def run_agent():
    """Main agent loop"""
    global INSTANCE_ID
    
    if not INSTANCE_ID:
        logger.info("No INSTANCE_ID set, trying to fetch from EC2 metadata...")
        INSTANCE_ID = get_instance_id_from_metadata()
        
        if not INSTANCE_ID:
            logger.warning("Could not get instance ID from metadata. Using hostname as ID.")
            INSTANCE_ID = socket.gethostname()
    
    logger.info(f"Starting CloudHealth Local Metrics Agent")
    logger.info(f"  Instance ID: {INSTANCE_ID}")
    logger.info(f"  Backend URL: {BACKEND_URL}")
    logger.info(f"  Interval: {INTERVAL} seconds")
    logger.info("-" * 50)
    
    collector = MetricsCollector()
    
    time.sleep(2)
    
    sent_count = 0
    fail_count = 0
    
    while True:
        try:
            metrics = collector.collect()
            metrics['instance_id'] = INSTANCE_ID
            
            if send_metrics_to_backend(metrics):
                sent_count += 1
            else:
                fail_count += 1
            
            if sent_count % 10 == 0:
                logger.info(f"Stats - Sent: {sent_count}, Failed: {fail_count}")
                
        except KeyboardInterrupt:
            logger.info("Agent stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in agent loop: {e}")
        
        time.sleep(INTERVAL)


def run_daemon():
    """Run agent as a daemon in background"""
    import signal
    import atexit
    
    def cleanup():
        logger.info("Cleaning up agent...")
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, stopping...")
        sys.exit(0)
    
    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    run_agent()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--daemon':
            run_daemon()
        elif sys.argv[1] == '--test':
            print("Testing metric collection...")
            collector = MetricsCollector()
            time.sleep(2)
            metrics = collector.collect()
            metrics['instance_id'] = INSTANCE_ID or 'test-instance'
            print(json.dumps(metrics, indent=2))
        elif sys.argv[1] == '--help':
            print(__doc__)
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Usage: python local_metrics_agent.py [--daemon|--test|--help]")
    else:
        run_agent()