#!/bin/bash
# =============================================================================
# Matrix Build Launcher - Launch EC2, copy script, run build
# =============================================================================
# Usage: 
#   ./launch_matrix_build.sh france "-5.5,41.0,10.0,51.5"
#   ./launch_matrix_build.sh paris "2.0,48.5,2.6,49.0"
# =============================================================================

set -e

NAME="${1:-france}"
BBOX="${2:--5.5,41.0,10.0,51.5}"

echo "=============================================="
echo "🌍 Matrix Build Launcher"
echo "=============================================="
echo "Region: $NAME"
echo "BBox: $BBOX"
echo "=============================================="

# Configuration
INSTANCE_TYPE="r7i.metal-48xl"
AMI_ID="ami-0030e4319cbf4dbf2"  # Ubuntu 22.04 us-east-1
KEY_NAME="matrix-builder"
KEY_PATH="$HOME/.ssh/matrix-builder.pem"
SECURITY_GROUP="sg-07c6ca4e8bbcd8139"
AZ="us-east-1b"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_SCRIPT="$SCRIPT_DIR/../etl/build_earth_matrix.py"

# User data just installs dependencies
read -r -d '' USER_DATA << 'EOF' || true
#!/bin/bash
set -e
exec > >(tee /var/log/setup.log) 2>&1
echo "=== Setup Started: $(date) ==="

apt-get update -y
apt-get install -y python3 python3-pip python3-venv awscli

python3 -m venv /opt/matrix-env
source /opt/matrix-env/bin/activate
pip install --upgrade pip
pip install duckdb pyarrow pandas tqdm boto3 h3

mkdir -p /opt/matrix-build
chown ubuntu:ubuntu /opt/matrix-build

echo "SETUP_COMPLETE" > /tmp/setup_status.txt
echo "=== Setup Complete: $(date) ==="
EOF

echo "Launching EC2 instance..."

INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SECURITY_GROUP" \
    --placement AvailabilityZone="$AZ" \
    --user-data "$USER_DATA" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":500,"VolumeType":"gp3","Iops":16000,"Throughput":1000}}]' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=matrix-build-$NAME}]" \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "Instance ID: $INSTANCE_ID"
echo "Waiting for instance to start..."

aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"

PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

echo "Public IP: $PUBLIC_IP"
echo "Waiting for SSH to be ready..."

# Wait for SSH
for i in {1..30}; do
    if ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no -o ConnectTimeout=5 ubuntu@"$PUBLIC_IP" "echo SSH_OK" 2>/dev/null; then
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 10
done

echo "Waiting for setup to complete..."

# Wait for setup
for i in {1..60}; do
    if ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no ubuntu@"$PUBLIC_IP" "cat /tmp/setup_status.txt 2>/dev/null" | grep -q "SETUP_COMPLETE"; then
        break
    fi
    echo "  Installing dependencies... ($i/60)"
    sleep 10
done

echo "Copying build script..."
scp -i "$KEY_PATH" -o StrictHostKeyChecking=no "$BUILD_SCRIPT" ubuntu@"$PUBLIC_IP":/opt/matrix-build/

echo "Starting build..."
ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no ubuntu@"$PUBLIC_IP" << REMOTE
source /opt/matrix-env/bin/activate
cd /opt/matrix-build
nohup python3 build_earth_matrix.py --bbox="$BBOX" --output="/opt/matrix-build/${NAME}_matrix_h11.parquet" > /opt/matrix-build/build.log 2>&1 &
echo "Build started in background"
REMOTE

echo ""
echo "=============================================="
echo "✅ Build Started!"
echo "=============================================="
echo "Instance ID: $INSTANCE_ID"
echo "Public IP:   $PUBLIC_IP"
echo ""
echo "To monitor:"
echo "  ssh -i $KEY_PATH ubuntu@$PUBLIC_IP 'tail -f /opt/matrix-build/build.log'"
echo ""
echo "To terminate when done:"
echo "  aws ec2 terminate-instances --instance-ids $INSTANCE_ID"
echo "=============================================="
