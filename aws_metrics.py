import os
import random
import boto3
from datetime import datetime, timedelta
from botocore.exceptions import ClientError, NoCredentialsError

USE_AWS = None

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
TARGET_INSTANCE_ID = os.getenv('TARGET_INSTANCE_ID', '')

AWS_CONFIG = {
    'region_name': AWS_REGION
}

def get_instance_id():
    """Get EC2 instance ID from metadata service"""
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
            print(f"[OK] Detected Instance ID from metadata: {TARGET_INSTANCE_ID}")
            return TARGET_INSTANCE_ID
    except Exception as e:
        print(f"[WARN] Could not get instance ID from metadata: {e}")
        return TARGET_INSTANCE_ID

def check_aws_credentials():
    """
    Check if AWS credentials are available via:
    1. EC2 Instance Profile (IAM role)
    2. Environment variables
    3. AWS credentials file
    
    Uses boto3's default credential resolution - no manual credentials needed.
    """
    global USE_AWS
    if USE_AWS is not None:
        return USE_AWS
    
    try:
        sts = boto3.client('sts', region_name=AWS_REGION)
        identity = sts.get_caller_identity()
        arn = identity.get('Arn', 'Unknown')
        
        if 'instance-profile' in arn.lower() or 'role' in arn.lower():
            print(f"[OK] Using EC2 Instance Profile (IAM Role)")
        else:
            print(f"[OK] AWS credentials detected: {arn}")
        
        USE_AWS = True
        get_instance_id()
        return True
        
    except NoCredentialsError:
        USE_AWS = False
        print(f"[WARN] No AWS credentials found")
        return False
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code in ['ExpiredToken', 'InvalidClientTokenId']:
            USE_AWS = False
            print(f"[WARN] AWS credentials expired or invalid")
            return False
        USE_AWS = False
        print(f"[WARN] AWS ClientError: {str(e)[:100]}")
        return False
    except Exception as e:
        USE_AWS = False
        print(f"[WARN] No AWS credentials configured - Running in mock mode")
        print(f"  (To use real AWS: configure AWS CLI or set AWS_ACCESS_KEY_ID environment variable)")
        return False

def get_cloudwatch_client():
    if not check_aws_credentials():
        return None
    try:
        return boto3.client('cloudwatch', region_name=AWS_REGION)
    except (ClientError, NoCredentialsError) as e:
        print(f"Error creating CloudWatch client: {e}")
        return None

def get_ec2_client():
    if not check_aws_credentials():
        return None
    try:
        return boto3.client('ec2', region_name=AWS_REGION)
    except (ClientError, NoCredentialsError) as e:
        print(f"Error creating EC2 client: {e}")
        return None

def get_ec2_describe_client():
    if not check_aws_credentials():
        return None
    try:
        return boto3.client('ec2', region_name=AWS_REGION)
    except Exception as e:
        print(f"Error creating EC2 describe client: {e}")
        return None

def fetch_ec2_metrics(instance_id=None, hours=24):
    """
    Fetch comprehensive metrics from AWS CloudWatch.
    
    If instance_id is provided, fetches real CloudWatch metrics.
    Otherwise returns mock data.
    
    Required IAM permissions:
    - cloudwatch:GetMetricStatistics
    - ec2:DescribeInstances
    - ec2:DescribeVolumes (for disk metrics)
    """
    if instance_id is None:
        instance_id = TARGET_INSTANCE_ID
    
    if not check_aws_credentials():
        return generate_mock_metrics(hours)
    
    client = get_cloudwatch_client()
    ec2 = get_ec2_describe_client()
    
    if client is None:
        return generate_mock_metrics(hours)
    
    try:
        if instance_id and ec2:
            response = ec2.describe_instances(InstanceIds=[instance_id])
            if not response.get('Reservations') or not response['Reservations'][0].get('Instances'):
                print(f"Instance {instance_id} not found")
                return generate_mock_metrics(hours)
        
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)
        
        metrics = {
            'cpu_utilization': get_cloudwatch_metric(client, instance_id, 'CPUUtilization', start_time, end_time),
            'cpu_credit_balance': get_cloudwatch_metric(client, instance_id, 'CPUCreditBalance', start_time, end_time),
            'cpu_credit_usage': get_cloudwatch_metric(client, instance_id, 'CPUCreditUsage', start_time, end_time),
            'network_in': get_cloudwatch_metric(client, instance_id, 'NetworkIn', start_time, end_time),
            'network_out': get_cloudwatch_metric(client, instance_id, 'NetworkOut', start_time, end_time),
            'network_packets_in': get_cloudwatch_metric(client, instance_id, 'NetworkPacketsIn', start_time, end_time),
            'network_packets_out': get_cloudwatch_metric(client, instance_id, 'NetworkPacketsOut', start_time, end_time),
            'disk_read_ops': get_cloudwatch_metric(client, instance_id, 'DiskReadOps', start_time, end_time),
            'disk_write_ops': get_cloudwatch_metric(client, instance_id, 'DiskWriteOps', start_time, end_time),
            'disk_read_bytes': get_cloudwatch_metric(client, instance_id, 'DiskReadBytes', start_time, end_time),
            'disk_write_bytes': get_cloudwatch_metric(client, instance_id, 'DiskWriteBytes', start_time, end_time),
        }
        
        memory_metrics = get_memory_metrics_from_cloudwatch(client, instance_id, start_time, end_time)
        if memory_metrics:
            metrics['memory_usage'] = memory_metrics.get('usage', [])
            metrics['memory_used'] = memory_metrics.get('used_bytes', [])
            metrics['memory_available'] = memory_metrics.get('available_bytes', [])
        
        disk_utilization = get_disk_utilization_from_cloudwatch(client, instance_id, start_time, end_time)
        metrics['disk_usage'] = disk_utilization.get('usage_percent', 50)
        metrics['disk_utilization'] = disk_utilization.get('utilization', [])
        
        instance_status = get_instance_status(ec2, instance_id)
        metrics['instance_status'] = instance_status
        
        return metrics
        
    except Exception as e:
        print(f"Error fetching AWS metrics: {e}")
        import traceback
        traceback.print_exc()
        return generate_mock_metrics(hours)

def get_ec2_instances():
    """Get list of EC2 instances for the account with full details"""
    if not check_aws_credentials():
        return []
    
    ec2 = get_ec2_client()
    if ec2 is None:
        return []
    
    try:
        response = ec2.describe_instances(
            Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
        )
        
        instances = []
        for reservation in response.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                instance_id = instance.get('InstanceId')
                
                name = 'Unnamed'
                for tag in instance.get('Tags', []):
                    if tag['Key'] == 'Name':
                        name = tag['Value']
                        break
                
                vpc_id = instance.get('VpcId', 'N/A')
                subnet_id = instance.get('SubnetId', 'N/A')
                private_ip = instance.get('PrivateIpAddress', 'N/A')
                public_ip = instance.get('PublicIpAddress', 'N/A')
                
                security_groups = [sg.get('GroupName', 'N/A') for sg in instance.get('SecurityGroups', [])]
                
                volumes = instance.get('BlockDeviceMappings', [])
                ebs_devices = []
                for vol in volumes:
                    ebs = vol.get('Ebs', {})
                    ebs_devices.append({
                        'volume_id': ebs.get('VolumeId', 'N/A'),
                        'device': ebs.get('DeviceName', 'N/A')
                    })
                
                instances.append({
                    'id': instance_id,
                    'name': name,
                    'type': instance.get('InstanceType'),
                    'state': instance.get('State', {}).get('Name'),
                    'region': AWS_REGION,
                    'vpc_id': vpc_id,
                    'subnet_id': subnet_id,
                    'private_ip': private_ip,
                    'public_ip': public_ip,
                    'security_groups': security_groups,
                    'ebs_volumes': ebs_devices,
                    'ami_id': instance.get('ImageId', 'N/A'),
                    'architecture': instance.get('Architecture', 'N/A'),
                    'hypervisor': instance.get('Hypervisor', 'N/A'),
                })
        
        print(f"[OK] Found {len(instances)} EC2 instance(s)")
        return instances
    except Exception as e:
        print(f"Error fetching EC2 instances: {e}")
        return []

def get_instance_details(instance_id):
    """Get detailed information about a specific EC2 instance"""
    if not check_aws_credentials():
        return None
    
    ec2 = get_ec2_client()
    if ec2 is None:
        return None
    
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        
        if not response.get('Reservations') or not response['Reservations'][0].get('Instances'):
            return None
        
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
            'state_code': instance.get('State', {}).get('Code'),
            'private_ip': instance.get('PrivateIpAddress'),
            'public_ip': instance.get('PublicIpAddress'),
            'vpc_id': instance.get('VpcId'),
            'subnet_id': instance.get('SubnetId'),
            'ami_id': instance.get('ImageId'),
            'architecture': instance.get('Architecture'),
            'hypervisor': instance.get('Hypervisor'),
            'root_device': instance.get('RootDeviceName'),
            'root_device_type': instance.get('RootDeviceType'),
            'security_groups': [sg.get('GroupName') for sg in instance.get('SecurityGroups', [])],
            'tags': {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])},
        }
        
    except Exception as e:
        print(f"Error fetching instance details: {e}")
        return None

def get_instance_status(ec2_client, instance_id):
    """Get instance status including system status and instance status"""
    if not ec2_client:
        return {'status': 'unknown', 'system_status': 'unknown', 'instance_status': 'unknown'}
    
    try:
        response = ec2_client.describe_instance_status(
            InstanceIds=[instance_id],
            IncludeAllInstances=True
        )
        
        if response.get('InstanceStatuses'):
            status = response['InstanceStatuses'][0]
            return {
                'status': status.get('InstanceState', {}).get('Name', 'unknown'),
                'system_status': status.get('SystemStatus', {}).get('Status', 'unknown'),
                'instance_status': status.get('InstanceStatus', {}).get('Status', 'unknown'),
                'status_checks': {
                    'system': status.get('SystemStatus', {}).get('Status', 'unknown'),
                    'instance': status.get('InstanceStatus', {}).get('Status', 'unknown')
                }
            }
        
        return {'status': 'unknown', 'system_status': 'unknown', 'instance_status': 'unknown'}
    except Exception as e:
        print(f"Error getting instance status: {e}")
        return {'status': 'unknown', 'system_status': 'unknown', 'instance_status': 'unknown'}

def get_memory_metrics_from_cloudwatch(client, instance_id, start_time, end_time):
    """Get memory metrics from CloudWatch (requires CloudWatch Agent)"""
    try:
        response = client.get_metric_statistics(
            Namespace='CWAgent',
            MetricName='mem_used_percent',
            Dimensions=[
                {'Name': 'InstanceId', 'Value': instance_id},
                {'Name': 'engine', 'Value': 'amazon-cloudwatch-agent'}
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=3600,
            Statistics=['Average', 'Maximum', 'Minimum']
        )
        
        datapoints = response.get('Datapoints', [])
        if datapoints:
            return {
                'usage': [{'timestamp': dp['Timestamp'], 'value': dp['Average']} for dp in sorted(datapoints, key=lambda x: x['Timestamp'])],
                'used_bytes': [{'timestamp': dp['Timestamp'], 'value': dp.get('Maximum', 0)} for dp in sorted(datapoints, key=lambda x: x['Timestamp'])],
                'available_bytes': [{'timestamp': dp['Timestamp'], 'value': dp.get('Minimum', 0)} for dp in sorted(datapoints, key=lambda x: x['Timestamp'])]
            }
    except Exception as e:
        pass
    
    try:
        response = client.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='MemoryUtilization',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=3600,
            Statistics=['Average']
        )
        
        datapoints = response.get('Datapoints', [])
        if datapoints:
            return {
                'usage': [{'timestamp': dp['Timestamp'], 'value': dp['Average']} for dp in sorted(datapoints, key=lambda x: x['Timestamp'])],
                'used_bytes': [],
                'available_bytes': []
            }
    except Exception as e:
        pass
    
    return None

def get_disk_utilization_from_cloudwatch(client, instance_id, start_time, end_time):
    """Get disk utilization from CloudWatch (requires CloudWatch Agent)"""
    try:
        response = client.get_metric_statistics(
            Namespace='CWAgent',
            MetricName='disk_used_percent',
            Dimensions=[
                {'Name': 'InstanceId', 'Value': instance_id}
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=3600,
            Statistics=['Average', 'Maximum']
        )
        
        datapoints = response.get('Datapoints', [])
        if datapoints:
            avg_usage = sum(dp['Average'] for dp in datapoints) / len(datapoints)
            return {
                'usage_percent': min(100, avg_usage),
                'utilization': [{'timestamp': dp['Timestamp'], 'value': dp['Average']} for dp in sorted(datapoints, key=lambda x: x['Timestamp'])]
            }
    except Exception as e:
        pass
    
    try:
        response = client.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='DiskUtilization',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=3600,
            Statistics=['Average']
        )
        
        datapoints = response.get('Datapoints', [])
        if datapoints:
            avg_usage = sum(dp['Average'] for dp in datapoints) / len(datapoints)
            return {
                'usage_percent': min(100, avg_usage),
                'utilization': [{'timestamp': dp['Timestamp'], 'value': dp['Average']} for dp in sorted(datapoints, key=lambda x: x['Timestamp'])]
            }
    except Exception as e:
        pass
    
    return {'usage_percent': 50, 'utilization': []}

def get_cloudwatch_metric(client, instance_id, metric_name, start_time, end_time, period=3600, statistics=['Average']):
    """Fetch a single CloudWatch metric"""
    try:
        response = client.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName=metric_name,
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=period,
            Statistics=statistics
        )
        
        datapoints = response.get('Datapoints', [])
        return [{'timestamp': dp['Timestamp'], 'value': dp.get(statistics[0], 0)} for dp in sorted(datapoints, key=lambda x: x['Timestamp'])]
    except Exception as e:
        print(f"Error getting metric {metric_name}: {e}")
        return []

def get_ebs_volumes(instance_id):
    """Get EBS volume details for an instance"""
    if not check_aws_credentials():
        return []
    
    ec2 = get_ec2_client()
    if ec2 is None:
        return []
    
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        
        if not response.get('Reservations') or not response['Reservations'][0].get('Instances'):
            return []
        
        instance = response['Reservations'][0]['Instances'][0]
        volume_ids = []
        
        for bdm in instance.get('BlockDeviceMappings', []):
            volume_ids.append(bdm.get('Ebs', {}).get('VolumeId'))
        
        if not volume_ids:
            return []
        
        volumes_response = ec2.describe_volumes(VolumeIds=volume_ids)
        
        volumes = []
        for vol in volumes_response.get('Volumes', []):
            volumes.append({
                'volume_id': vol.get('VolumeId'),
                'size': vol.get('Size'),
                'volume_type': vol.get('VolumeType'),
                'state': vol.get('State'),
                'encrypted': vol.get('Encrypted'),
                'iops': vol.get('Iops'),
                'throughput': vol.get('Throughput'),
                'create_time': str(vol.get('CreateTime')),
                'availability_zone': vol.get('AvailabilityZone'),
                'tags': {tag['Key']: tag['Value'] for tag in vol.get('Tags', [])}
            })
        
        return volumes
        
    except Exception as e:
        print(f"Error fetching EBS volumes: {e}")
        return []

def estimate_memory_usage(cpu_data):
    """Estimate memory usage based on CPU patterns when CloudWatch agent not available"""
    if not cpu_data:
        return 65
    
    avg_cpu = sum(dp['value'] for dp in cpu_data) / len(cpu_data) if cpu_data else 50
    base_memory = 40
    memory_factor = (avg_cpu / 100) * 35
    return min(95, int(base_memory + memory_factor + random.randint(-5, 5)))

def estimate_disk_usage(disk_data):
    """Estimate disk usage when CloudWatch agent not available"""
    return random.randint(45, 65)

def get_current_metrics():
    """Get current real-time metrics from AWS or mock"""
    if not check_aws_credentials():
        return generate_mock_metrics(1)
    
    return fetch_ec2_metrics(TARGET_INSTANCE_ID, 1)

def generate_mock_metrics(hours=24):
    """Generate realistic mock metrics for demonstration"""
    import random
    
    now = datetime.now()
    cpu_data = []
    memory_data = []
    network_data = []
    disk_data = []
    
    base_cpu = 55
    base_memory = 60
    
    for i in range(hours):
        timestamp = now - timedelta(hours=hours - 1 - i)
        
        hour_factor = 1 + 0.3 * (1 if 9 <= timestamp.hour <= 17 else 0)
        
        cpu = min(98, max(20, base_cpu * hour_factor + random.randint(-10, 15)))
        memory = min(95, max(30, base_memory * hour_factor * 0.9 + random.randint(-8, 10)))
        
        network_in = random.randint(80000, 450000)
        network_out = random.randint(40000, 180000)
        disk_io = random.randint(800, 4500)
        
        cpu_data.append({
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M'),
            'value': int(cpu)
        })
        
        memory_data.append({
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M'),
            'value': int(memory)
        })
        
        network_data.append({
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M'),
            'network_in': network_in,
            'network_out': network_out
        })
        
        disk_data.append({
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M'),
            'disk_io': disk_io
        })
    
    current_cpu = cpu_data[-1]['value'] if cpu_data else 65
    current_memory = memory_data[-1]['value'] if memory_data else 72
    current_disk = random.randint(50, 60)
    uptime = random.randint(280000, 300000)
    
    return {
        'cpu_utilization': cpu_data,
        'memory_usage': memory_data,
        'disk_usage': current_disk,
        'network_in': network_data,
        'network_out': network_data,
        'disk_io': disk_data,
        'uptime_seconds': uptime,
        'current_cpu': current_cpu,
        'current_memory': current_memory
    }