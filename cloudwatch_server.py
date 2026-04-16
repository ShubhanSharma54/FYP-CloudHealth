#!/usr/bin/env python3
"""
CloudHealth EC2 Monitoring Server
Designed for AWS Academy Learner Lab - uses EC2 Instance Profile (no access keys required)

Usage:
    python3 cloudwatch_server.py

Requirements:
    pip install flask boto3

The server:
- Automatically detects instance ID from EC2 metadata
- Uses boto3 with IAM role (LabInstanceProfile) - NO access keys needed
- Fetches metrics from CloudWatch
- Has fallback to system commands if CloudWatch Agent not installed
"""

import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify, request

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
TARGET_INSTANCE_ID = None

def get_instance_id():
    """Get EC2 instance ID from metadata service (works on EC2)"""
    global TARGET_INSTANCE_ID
    
    if TARGET_INSTANCE_ID:
        return TARGET_INSTANCE_ID
    
    try:
        import urllib.request
        url = 'http://169.254.169.254/latest/meta-data/instance-id'
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'CloudHealth-Monitor/1.0')
        
        with urllib.request.urlopen(req, timeout=3) as response:
            TARGET_INSTANCE_ID = response.read().decode('utf-8')
            logger.info(f"Detected Instance ID: {TARGET_INSTANCE_ID}")
            return TARGET_INSTANCE_ID
    except Exception as e:
        logger.warning(f"Could not get instance ID from metadata: {e}")
        TARGET_INSTANCE_ID = os.getenv('TARGET_INSTANCE_ID', 'i-07aafc7c37daf9563')
        return TARGET_INSTANCE_ID

def get_cloudwatch_client():
    """Create CloudWatch client - uses IAM role automatically"""
    try:
        return boto3.client('cloudwatch', region_name=AWS_REGION)
    except Exception as e:
        logger.error(f"Failed to create CloudWatch client: {e}")
        return None

def get_ec2_client():
    """Create EC2 client - uses IAM role automatically"""
    try:
        return boto3.client('ec2', region_name=AWS_REGION)
    except Exception as e:
        logger.error(f"Failed to create EC2 client: {e}")
        return None

def fetch_cloudwatch_metric(client, instance_id, metric_name, namespace='AWS/EC2', duration_minutes=30, period=60):
    """Fetch a single metric from CloudWatch"""
    try:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=duration_minutes)
        
        kwargs = {
            'Namespace': namespace,
            'MetricName': metric_name,
            'StartTime': start_time,
            'EndTime': end_time,
            'Period': period,
            'Statistics': ['Average', 'Maximum', 'Minimum'],
            'Dimensions': [{'Name': 'InstanceId', 'Value': instance_id}]
        }
        
        response = client.get_metric_statistics(**kwargs)
        datapoints = response.get('Datapoints', [])
        
        if not datapoints:
            return []
        
        return sorted(datapoints, key=lambda x: x['Timestamp'])
    
    except ClientError as e:
        logger.warning(f"CloudWatch error for {metric_name}: {e}")
        return []
    except Exception as e:
        logger.error(f"Error fetching {metric_name}: {e}")
        return []

def format_metric_data(datapoints, value_key='Average'):
    """Format CloudWatch datapoints for frontend"""
    result = []
    for dp in datapoints:
        timestamp = dp.get('Timestamp')
        if isinstance(timestamp, datetime):
            timestamp = timestamp.strftime('%H:%M')
        
        result.append({
            'time': timestamp,
            'value': round(dp.get(value_key, 0), 2)
        })
    
    return result

def get_current_instance_metadata():
    """Get current instance metadata"""
    instance_id = get_instance_id()
    
    ec2 = get_ec2_client()
    if not ec2:
        return {'instance_id': instance_id, 'error': 'Cannot connect to EC2'}
    
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        if not response.get('Reservations') or not response['Reservations'][0].get('Instances'):
            return {'instance_id': instance_id, 'error': 'Instance not found'}
        
        instance = response['Reservations'][0]['Instances'][0]
        
        name = 'Unnamed'
        for tag in instance.get('Tags', []):
            if tag['Key'] == 'Name':
                name = tag['Value']
                break
        
        return {
            'instance_id': instance.get('InstanceId'),
            'name': name,
            'instance_type': instance.get('InstanceType'),
            'state': instance.get('State', {}).get('Name'),
            'private_ip': instance.get('PrivateIpAddress'),
            'public_ip': instance.get('PublicIpAddress'),
            'region': AWS_REGION
        }
    
    except Exception as e:
        logger.error(f"Error getting instance metadata: {e}")
        return {'instance_id': instance_id, 'error': str(e)}

@app.route('/api/status')
def status():
    """Health check endpoint"""
    instance_id = get_instance_id()
    metadata = get_current_instance_metadata()
    
    return jsonify({
        'status': 'running',
        'instance_id': instance_id,
        'instance': metadata,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/cpu')
def cpu_metrics():
    """Get CPU utilization from CloudWatch"""
    instance_id = get_instance_id()
    client = get_cloudwatch_client()
    
    if not client:
        return jsonify({'error': 'CloudWatch not available', 'source': 'error'}), 503
    
    datapoints = fetch_cloudwatch_metric(client, instance_id, 'CPUUtilization')
    
    if not datapoints:
        return jsonify({
            'error': 'No CPU metrics available',
            'hint': 'Ensure CloudWatch is enabled for this instance',
            'source': 'cloudwatch'
        })
    
    data = format_metric_data(datapoints)
    current = data[-1]['value'] if data else 0
    
    return jsonify({
        'metric': 'CPUUtilization',
        'current': current,
        'data': data,
        'source': 'cloudwatch',
        'instance_id': instance_id
    })

@app.route('/api/memory')
def memory_metrics():
    """Get Memory utilization - tries CWAgent first, then system fallback"""
    instance_id = get_instance_id()
    client = get_cloudwatch_client()
    
    if client:
        datapoints = fetch_cloudwatch_metric(
            client, instance_id, 
            'mem_used_percent', 
            namespace='CWAgent',
            duration_minutes=30
        )
        
        if datapoints:
            data = format_metric_data(datapoints)
            current = data[-1]['value'] if data else 0
            
            return jsonify({
                'metric': 'MemoryUtilization',
                'current': current,
                'data': data,
                'source': 'cwagent',
                'instance_id': instance_id
            })
    
    try:
        import psutil
        mem = psutil.virtual_memory()
        
        return jsonify({
            'metric': 'MemoryUtilization',
            'current': round(mem.percent, 2),
            'data': [{'time': datetime.now().strftime('%H:%M'), 'value': round(mem.percent, 2)}],
            'source': 'psutil',
            'instance_id': instance_id,
            'note': 'Using local psutil (CloudWatch Agent not installed)'
        })
    except ImportError:
        return jsonify({
            'error': 'Memory metrics unavailable',
            'hint': 'Install CloudWatch Agent or run: pip install psutil',
            'source': 'unavailable'
        })

@app.route('/api/network')
def network_metrics():
    """Get Network I/O from CloudWatch"""
    instance_id = get_instance_id()
    client = get_cloudwatch_client()
    
    if not client:
        return jsonify({'error': 'CloudWatch not available', 'source': 'error'}), 503
    
    network_in = fetch_cloudwatch_metric(client, instance_id, 'NetworkIn')
    network_out = fetch_cloudwatch_metric(client, instance_id, 'NetworkOut')
    
    result = {
        'source': 'cloudwatch',
        'instance_id': instance_id,
        'network_in': format_metric_data(network_in),
        'network_out': format_metric_data(network_out)
    }
    
    if network_in:
        result['current_in'] = network_in[-1].get('Average', 0)
        result['current_out'] = network_out[-1].get('Average', 0) if network_out else 0
    
    return jsonify(result)

@app.route('/api/disk')
def disk_metrics():
    """Get Disk I/O from CloudWatch"""
    instance_id = get_instance_id()
    client = get_cloudwatch_client()
    
    if not client:
        return jsonify({'error': 'CloudWatch not available', 'source': 'error'}), 503
    
    disk_read = fetch_cloudwatch_metric(client, instance_id, 'DiskReadBytes')
    disk_write = fetch_cloudwatch_metric(client, instance_id, 'DiskWriteBytes')
    
    result = {
        'source': 'cloudwatch',
        'instance_id': instance_id,
        'disk_read': format_metric_data(disk_read, 'Average'),
        'disk_write': format_metric_data(disk_write, 'Average')
    }
    
    if disk_read:
        result['current_read'] = disk_read[-1].get('Average', 0)
        result['current_write'] = disk_write[-1].get('Average', 0) if disk_write else 0
    
    return jsonify(result)

@app.route('/api/all')
def all_metrics():
    """Get all metrics in one request"""
    instance_id = get_instance_id()
    client = get_cloudwatch_client()
    
    response = {
        'instance_id': instance_id,
        'timestamp': datetime.now().isoformat()
    }
    
    if client:
        response['cpu'] = {
            'data': format_metric_data(fetch_cloudwatch_metric(client, instance_id, 'CPUUtilization')),
            'source': 'cloudwatch'
        }
        
        response['network'] = {
            'in': format_metric_data(fetch_cloudwatch_metric(client, instance_id, 'NetworkIn')),
            'out': format_metric_data(fetch_cloudwatch_metric(client, instance_id, 'NetworkOut')),
            'source': 'cloudwatch'
        }
        
        response['disk'] = {
            'read': format_metric_data(fetch_cloudwatch_metric(client, instance_id, 'DiskReadBytes')),
            'write': format_metric_data(fetch_cloudwatch_metric(client, instance_id, 'DiskWriteBytes')),
            'source': 'cloudwatch'
        }
        
        mem_datapoints = fetch_cloudwatch_metric(client, instance_id, 'mem_used_percent', namespace='CWAgent')
        if mem_datapoints:
            response['memory'] = {
                'data': format_metric_data(mem_datapoints),
                'source': 'cwagent'
            }
    
    if 'memory' not in response:
        try:
            import psutil
            mem = psutil.virtual_memory()
            response['memory'] = {
                'data': [{'time': datetime.now().strftime('%H:%M'), 'value': round(mem.percent, 2)}],
                'source': 'psutil'
            }
        except ImportError:
            response['memory'] = {'data': [], 'source': 'unavailable'}
    
    return jsonify(response)

@app.route('/api/instance')
def instance_info():
    """Get instance information"""
    return jsonify(get_current_instance_metadata())

if __name__ == '__main__':
    logger.info("Starting CloudHealth EC2 Monitoring Server")
    logger.info(f"Region: {AWS_REGION}")
    logger.info("Using EC2 Instance Profile (no access keys required)")
    
    instance_id = get_instance_id()
    logger.info(f"Target Instance: {instance_id}")
    
    app.run(host='0.0.0.0', port=5000, debug=False)