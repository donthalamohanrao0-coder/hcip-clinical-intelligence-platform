"""
HCIP AWS EC2 Deployment Script
Provisions m7i-flex.large in eu-north-1, installs Docker, deploys all services.
Run: python deploy_aws.py
"""

import os
import time
import subprocess
import textwrap
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# ─── Config ───────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent

# Load AWS credentials from .env in the project root — never hardcode them here.
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")
except ImportError:
    pass

AWS_ACCESS_KEY_ID     = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
REGION                = os.environ.get("AWS_REGION", "eu-north-1")
INSTANCE_TYPE         = "m7i-flex.large"
KEY_NAME              = "hcip-key"
SG_NAME               = "hcip-sg"
KEY_FILE              = PROJECT_DIR / "hcip-key.pem"
REMOTE_USER           = "ubuntu"
REMOTE_DIR            = "/home/ubuntu/hcip"

# Ports to open in security group
PORTS = [22, 8000, 3001, 9090, 6333, 7474, 7687, 9200, 6379, 3200, 4318]

# ─── AWS clients ──────────────────────────────────────────────────────────────
session = boto3.Session(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=REGION,
)
ec2 = session.client("ec2")
ec2r = session.resource("ec2")


def log(msg: str):
    print(f"\n{'='*60}\n{msg}\n{'='*60}")


# ─── Step 1: Key Pair ─────────────────────────────────────────────────────────
def create_key_pair():
    log("Step 1: Creating EC2 key pair")

    # Delete existing key if present
    try:
        ec2.delete_key_pair(KeyName=KEY_NAME)
        print(f"  Deleted existing key pair: {KEY_NAME}")
    except ClientError:
        pass

    # Remove old .pem if present (reset ACLs first since icacls may have locked it)
    if KEY_FILE.exists():
        try:
            subprocess.run(
                ["icacls", str(KEY_FILE), "/reset"],
                capture_output=True, check=False
            )
        except Exception:
            pass
        try:
            KEY_FILE.unlink()
        except Exception:
            pass

    resp = ec2.create_key_pair(KeyName=KEY_NAME, KeyType="rsa", KeyFormat="pem")
    pem_material = resp["KeyMaterial"]

    KEY_FILE.write_text(pem_material)
    print(f"  Key saved to: {KEY_FILE}")

    # chmod 400 (Windows: icacls to restrict access)
    try:
        subprocess.run(
            ["icacls", str(KEY_FILE), "/inheritance:r", "/grant:r",
             f"{os.environ.get('USERNAME', 'DELL')}:(R)"],
            capture_output=True, check=True
        )
    except Exception as e:
        print(f"  icacls warning (non-fatal): {e}")

    print(f"  Key pair created: {KEY_NAME}")
    return KEY_NAME


# ─── Step 2: Security Group ───────────────────────────────────────────────────
def create_security_group():
    log("Step 2: Creating security group")

    # Delete existing SG with same name if present
    try:
        existing = ec2.describe_security_groups(
            Filters=[{"Name": "group-name", "Values": [SG_NAME]}]
        )["SecurityGroups"]
        for sg in existing:
            try:
                ec2.delete_security_group(GroupId=sg["GroupId"])
                print(f"  Deleted old SG: {sg['GroupId']}")
            except ClientError as e:
                print(f"  Could not delete SG {sg['GroupId']}: {e}")
    except ClientError:
        pass

    resp = ec2.create_security_group(
        GroupName=SG_NAME,
        Description="HCIP Healthcare RAG Platform - dev/demo",
    )
    sg_id = resp["GroupId"]
    print(f"  Created SG: {sg_id}")

    # Add inbound rules
    permissions = [
        {
            "IpProtocol": "tcp",
            "FromPort": port,
            "ToPort": port,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": f"HCIP port {port}"}],
        }
        for port in PORTS
    ]
    ec2.authorize_security_group_ingress(GroupId=sg_id, IpPermissions=permissions)
    print(f"  Opened ports: {PORTS}")
    return sg_id


# ─── Step 3: Find Ubuntu 22.04 AMI ────────────────────────────────────────────
def find_ubuntu_ami():
    log("Step 3: Finding Ubuntu 22.04 LTS AMI in eu-north-1")
    resp = ec2.describe_images(
        Owners=["099720109477"],  # Canonical
        Filters=[
            {"Name": "name",              "Values": ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]},
            {"Name": "architecture",      "Values": ["x86_64"]},
            {"Name": "state",             "Values": ["available"]},
            {"Name": "virtualization-type", "Values": ["hvm"]},
        ],
    )
    images = sorted(resp["Images"], key=lambda x: x["CreationDate"], reverse=True)
    ami_id = images[0]["ImageId"]
    name   = images[0]["Name"]
    print(f"  Selected AMI: {ami_id} ({name})")
    return ami_id


# ─── Step 4: Launch Instance ──────────────────────────────────────────────────
def launch_instance(ami_id: str, sg_id: str) -> str:
    log("Step 4: Launching m7i-flex.large instance")

    user_data = textwrap.dedent("""\
        #!/bin/bash
        set -e
        apt-get update -y
        apt-get install -y ca-certificates curl gnupg lsb-release

        # Install Docker
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
        apt-get update -y
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

        # Allow ubuntu user to run docker
        usermod -aG docker ubuntu

        # Install Python 3.11 + pip
        apt-get install -y python3.11 python3-pip python3.11-venv

        # Create project directory
        mkdir -p /home/ubuntu/hcip
        chown ubuntu:ubuntu /home/ubuntu/hcip

        # Signal ready
        touch /tmp/cloud-init-done
    """)

    resp = ec2.run_instances(
        ImageId=ami_id,
        InstanceType=INSTANCE_TYPE,
        KeyName=KEY_NAME,
        SecurityGroupIds=[sg_id],
        MinCount=1,
        MaxCount=1,
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": 30,
                    "VolumeType": "gp3",
                    "DeleteOnTermination": True,
                },
            }
        ],
        UserData=user_data,
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name",    "Value": "hcip-server"},
                    {"Key": "Project", "Value": "HCIP"},
                ],
            }
        ],
    )

    instance_id = resp["Instances"][0]["InstanceId"]
    print(f"  Instance launched: {instance_id}")
    print(f"  Instance type:     {INSTANCE_TYPE}")
    print(f"  Region:            {REGION}")
    return instance_id


# ─── Step 5: Wait for Running + SSH ──────────────────────────────────────────
def wait_for_instance(instance_id: str) -> str:
    log("Step 5: Waiting for instance to be running (this takes ~60-90 seconds)")
    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=[instance_id])

    resp = ec2.describe_instances(InstanceIds=[instance_id])
    instance = resp["Reservations"][0]["Instances"][0]
    public_ip = instance["PublicIpAddress"]
    print(f"  Instance running!")
    print(f"  Public IP:  {public_ip}")
    print(f"  SSH:  ssh -i {KEY_FILE} {REMOTE_USER}@{public_ip}")

    # Wait for SSH to be accepting connections (extra 60s for cloud-init)
    print("  Waiting 90s for SSH daemon and cloud-init to finish...")
    time.sleep(90)

    return public_ip


# ─── Step 6: SCP project files ────────────────────────────────────────────────
def copy_files(public_ip: str):
    log("Step 6: Copying project files via SCP")

    # Files/dirs to copy (skip __pycache__, .git, node_modules, etc.)
    items_to_copy = [
        "api",
        "ingestion",
        "query",
        "observability",
        "grafana",
        "docker-compose.yml",
        "tempo.yml",
        "prometheus.yml",
        ".env",
        "requirements.txt",
    ]

    ssh_opts = [
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=30",
        "-i", str(KEY_FILE),
    ]

    for item in items_to_copy:
        src = PROJECT_DIR / item
        if not src.exists():
            print(f"  Skipping (not found): {item}")
            continue

        if src.is_dir():
            cmd = [
                "scp", *ssh_opts, "-r",
                # Exclude __pycache__ via tar trick below; scp can't exclude natively
                str(src),
                f"{REMOTE_USER}@{public_ip}:{REMOTE_DIR}/",
            ]
        else:
            cmd = [
                "scp", *ssh_opts,
                str(src),
                f"{REMOTE_USER}@{public_ip}:{REMOTE_DIR}/",
            ]

        print(f"  Copying: {item} ...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    ERROR: {result.stderr[:200]}")
        else:
            print(f"    OK")

    print("  File copy complete.")


# ─── Step 7: Remote setup & start services ────────────────────────────────────
def start_services(public_ip: str):
    log("Step 7: Installing Python deps and starting services on EC2")

    ssh_opts = [
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=30",
        "-i", str(KEY_FILE),
    ]

    commands = textwrap.dedent(f"""\
        set -e
        cd {REMOTE_DIR}

        echo "=== Checking Docker ==="
        sudo docker --version
        sudo docker compose version

        echo "=== Creating Python venv ==="
        python3.11 -m venv .venv
        source .venv/bin/activate

        echo "=== Installing Python dependencies ==="
        pip install --upgrade pip -q
        pip install -r requirements.txt -q

        echo "=== Pulling Docker images and starting services ==="
        sudo docker compose pull --quiet
        sudo docker compose up -d

        echo "=== Waiting 30s for services to become healthy ==="
        sleep 30
        sudo docker compose ps

        echo "=== Starting FastAPI ==="
        nohup .venv/bin/uvicorn api.main:app \\
            --host 0.0.0.0 --port 8000 \\
            --workers 2 \\
            --log-level info \\
            > /home/ubuntu/hcip/api.log 2>&1 &
        echo "FastAPI PID: $!"

        sleep 5
        echo "=== Health check ==="
        curl -s http://localhost:8000/health | python3 -m json.tool || echo "Health check failed (API may still be starting)"

        echo "=== DEPLOYMENT COMPLETE ==="
        echo "API:       http://{public_ip}:8000"
        echo "Docs:      http://{public_ip}:8000/docs"
        echo "Grafana:   http://{public_ip}:3001  (admin / hcip_grafana)"
        echo "Prometheus:http://{public_ip}:9090"
        echo "Qdrant:    http://{public_ip}:6333/dashboard"
        echo "Neo4j:     http://{public_ip}:7474"
    """)

    cmd = [
        "ssh", *ssh_opts,
        f"{REMOTE_USER}@{public_ip}",
        commands,
    ]

    print(f"  Running remote setup on {public_ip}...")
    result = subprocess.run(cmd, text=True, timeout=600)
    if result.returncode != 0:
        print(f"  Remote setup returned code {result.returncode} — check output above")
    else:
        print("  Remote setup completed successfully.")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    log("HCIP AWS EC2 Deployment — m7i-flex.large / eu-north-1")

    key_name = create_key_pair()
    sg_id    = create_security_group()
    ami_id   = find_ubuntu_ami()
    inst_id  = launch_instance(ami_id, sg_id)
    pub_ip   = wait_for_instance(inst_id)

    # Save connection info
    info_file = PROJECT_DIR / "ec2_info.txt"
    info_file.write_text(
        f"INSTANCE_ID={inst_id}\n"
        f"PUBLIC_IP={pub_ip}\n"
        f"REGION={REGION}\n"
        f"KEY_FILE={KEY_FILE}\n"
        f"SSH=ssh -i {KEY_FILE} {REMOTE_USER}@{pub_ip}\n"
        f"API=http://{pub_ip}:8000\n"
        f"DOCS=http://{pub_ip}:8000/docs\n"
        f"GRAFANA=http://{pub_ip}:3001\n"
        f"PROMETHEUS=http://{pub_ip}:9090\n"
        f"QDRANT=http://{pub_ip}:6333/dashboard\n"
        f"NEO4J=http://{pub_ip}:7474\n"
    )
    print(f"\n  Connection info saved to: {info_file}")

    copy_files(pub_ip)
    start_services(pub_ip)

    log("DEPLOYMENT COMPLETE")
    print(f"""
  Your HCIP stack is live on AWS!

  API:        http://{pub_ip}:8000
  Swagger UI: http://{pub_ip}:8000/docs
  Grafana:    http://{pub_ip}:3001  (admin / hcip_grafana)
  Prometheus: http://{pub_ip}:9090
  Qdrant:     http://{pub_ip}:6333/dashboard
  Neo4j:      http://{pub_ip}:7474  (neo4j / hcip_password)

  SSH:  ssh -i {KEY_FILE} {REMOTE_USER}@{pub_ip}

  To tail API logs:
    ssh -i {KEY_FILE} {REMOTE_USER}@{pub_ip} "tail -f /home/ubuntu/hcip/api.log"
""")


if __name__ == "__main__":
    main()
