import os
import boto3

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

env = {}
with open(ENV_PATH) as f:
    for line in f:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"')

session = boto3.Session(
    aws_access_key_id=env.get('AWS_ACCESS_KEY_ID', ''),
    aws_secret_access_key=env.get('AWS_SECRET_ACCESS_KEY', ''),
    region_name='eu-north-1',
)
ec2 = session.client('ec2')

# Instance state
r = ec2.describe_instances(InstanceIds=['i-0be6a8a627f6e78af'])
inst = r['Reservations'][0]['Instances'][0]
print(f"State : {inst['State']['Name']}")
print(f"IP    : {inst.get('PublicIpAddress', 'N/A')}")
print(f"Type  : {inst['InstanceType']}")

# Status checks
s = ec2.describe_instance_status(InstanceIds=['i-0be6a8a627f6e78af'], IncludeAllInstances=True)
if s['InstanceStatuses']:
    st = s['InstanceStatuses'][0]
    print(f"Instance check : {st['InstanceStatus']['Status']}")
    print(f"System check   : {st['SystemStatus']['Status']}")
