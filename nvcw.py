# nvcw.py

# Simple tool that sends nvidia-smi info to AWS CloudWatch

import json
from datetime import datetime
import time
import argparse
from pynvml import *
import boto3

class nvml_context:
    '''Simple context manager wrapper for nvml init and shutdown methods. '''
    def __enter__(self):
        nvmlInit()
    def __exit__(self, type, value, tb):
        nvmlShutdown()

def get_device_info(device_index):
    '''Gets the device name, fan speed, temperature, power and memory usage for a given GPU device.
    Params:
        - device_index (int): The index of the GPU device.
    Returns: dict. A dictionary containing the device info.
    '''
    with nvml_context():
        handle = nvmlDeviceGetHandleByIndex(device_index)
        power_usage = nvmlDeviceGetPowerUsage(handle) / 1000
        power_limit = nvmlDeviceGetPowerManagementLimit(handle) / 1000
        memory_info = nvmlDeviceGetMemoryInfo(handle)
        memory_used = memory_info.used / (1024 * 1024)
        memory_total = memory_info.total / (1024 * 1024)
        device_info = {
            'index': device_index,
            'name': nvmlDeviceGetName(handle).decode('ascii'),
            'fan_speed': nvmlDeviceGetFanSpeed(handle),
            'temperature': nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU),
            'performance_state': nvmlDeviceGetPerformanceState(handle),
            'power': {
                'usage': power_usage,
                'limit': power_limit,
                'percent': power_usage / power_limit * 100
            },
            'memory': {
                'usage': memory_used,
                'limit': memory_total,
                'percent': memory_info.used / memory_info.total * 100
            }
        }
    return device_info

def get_device_infos():
    '''Gets the device info for all GPU devices in the system.
    Returns: list. The list of device info dictionaries.
    '''
    with nvml_context():
        device_infos = [get_device_info(i) for i in range(nvmlDeviceGetCount())]
    return device_infos

def _get_metric_data(metric_name, device_index, workstation, timestamp, value, unit='None'):
    return {
        'MetricName': metric_name,
        'Dimensions': [
            { 'Name': 'device_index', 'Value': str(device_index) },
            { 'Name': 'workstation', 'Value': workstation }
        ],
        'Timestamp': timestamp,
        'Value': value,
        'Unit': unit
    }

def metric_for_device(device_info, timestamp, workstation):
    '''Returns a CloudWatch metrics strucutre from a device info dictionary.
    Params:
        - device_info (dict): The device info dictionary returned by get_device_info method.
        - timestamp (datetime.datetime): The time stamp of the measurment.
        - workstation (str): The name of the workstation, to be used as CloudWatch dimension.
    Returns: list<dict>. A list of CloudWatch metrics structure.
    '''
    device_index = device_info['index']
    return [
        _get_metric_data('fan_speed', device_index, workstation, timestamp, device_info['fan_speed'], 'Percent'),
        _get_metric_data('temperature', device_index, workstation, timestamp, device_info['temperature'], 'None'),
        _get_metric_data('performance_state', device_index, workstation, timestamp, device_info['performance_state'], 'None'),
        _get_metric_data('memory_usage', device_index, workstation, timestamp, device_info['memory']['usage'], 'Megabytes'),
        _get_metric_data('memory_percent', device_index, workstation, timestamp, device_info['memory']['percent'], 'Percent'),
        _get_metric_data('power_usage', device_index, workstation, timestamp, device_info['power']['usage'], 'None'),
        _get_metric_data('power_percent', device_index, workstation, timestamp, device_info['power']['percent'], 'Percent')
    ]

def put_device_infos(cloudwatch_client, namespace, workstation):
    '''Queries the tracked parameters for all GPU devices in the system and sends them to CloudWatch.
    Params:
        cloudwatch_client (boto3.CloudWatch.Client): The CloudWatch client.
        namespace (str): The namespace of the CloudWatch metrics.
        workstation (str): The name of the workstation, to be used as CloudWatch dimension.
    Returns: list<dict>. The list of device infos.
    '''
    device_infos = get_device_infos()
    timestamp = datetime.utcnow()
    metrics = []
    for device_info in device_infos:
        metrics = metric_for_device(device_info, timestamp, workstation)
        for metric in metrics:
            params = {
                'Namespace': namespace,
                'MetricData': [metric]
            }
            cloudwatch_client.put_metric_data(**params)
    return device_infos

if __name__ == '__main__':
    namespace = 'nvcw'
    client = boto3.client('cloudwatch')
    parser = argparse.ArgumentParser(description='Logs some nvidia device parameters to AWS CloudWatch. ' +
                                     'Ensure you have an AWS account configured granted to write CloudWatch logs. ' +
                                     'You can configure the AWS account with the aws cli or with environment variables.')
    parser.add_argument('workstation', help='Name of the workstation')
    parser.add_argument('-i', '--interval', help='The logging interval in seconds. Defaults to 60. ', default=60, type=int)
    args = parser.parse_args()
    while True:
        device_infos = put_device_infos(client, namespace=namespace, workstation=args.workstation)
        print(json.dumps(device_infos))
        time.sleep(args.interval)
