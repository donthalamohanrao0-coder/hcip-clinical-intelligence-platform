import os
import time
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

print("Rebooting i-0be6a8a627f6e78af ...")
ec2.reboot_instances(InstanceIds=['i-0be6a8a627f6e78af'])
print("Reboot triggered. Waiting 60s for instance to come back...")
time.sleep(60)

for attempt in range(10):
    try:
        r = ec2.describe_instance_status(
            InstanceIds=['i-0be6a8a627f6e78af'],
            IncludeAllInstances=True,
        )
        if r['InstanceStatuses']:
            st = r['InstanceStatuses'][0]
            state = st['InstanceState']['Name']
            inst_ok = st['InstanceStatus']['Status']
            sys_ok  = st['SystemStatus']['Status']
            print(f"  [{attempt+1}] state={state} instance={inst_ok} system={sys_ok}")
            if state == 'running' and inst_ok == 'ok' and sys_ok == 'ok':
                print("Instance is back and healthy!")
                break
    except Exception as e:
        print(f"  [{attempt+1}] error: {e}")
    time.sleep(15)
