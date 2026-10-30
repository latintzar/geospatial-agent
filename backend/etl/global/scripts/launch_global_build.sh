#!/bin/bash
# =============================================================================
# Launch Global Earth Matrix Build on AWS (MAXED Schema)
# =============================================================================
#
# This script launches an m8i.96xlarge instance to build the global
# Earth Matrix with ALL 1,081 Level-3 POI categories (5,745 columns).
#
# Why m8i.96xlarge?
#   - 384 vCPUs (2× more than r7i) = process 1,081 categories faster
#   - 100 Gbps network (2× faster S3 reads)
#   - Extended k-rings: k=25 (Res 10), k=20 (Res 8) for better coverage
#   - Total cost: ~$165 on-demand (~8 hours runtime)
#
# Usage:
#   ./launch_global_build.sh                    # Use spot pricing (~$6/hr)
#   ./launch_global_build.sh --on-demand        # Use on-demand (~$20/hr)
#   ./launch_global_build.sh --dry-run          # Show what would be launched
#
# Prerequisites:
#   - AWS CLI configured with appropriate permissions
#   - EC2 key pair named 'earth-matrix-key' (or set KEY_NAME below)
#   - Security group allowing SSH (or set SECURITY_GROUP below)
#
# =============================================================================

set -e

# Configuration
INSTANCE_TYPE="m8i.96xlarge"          # 384 vCPU, 1.5TB RAM, 100Gbps
AMI_ID="ami-0c55b159cbfafe1f0"        # Amazon Linux 2023 x86_64
KEY_NAME="${KEY_NAME:-earth-matrix-key}"
SECURITY_GROUP="${SECURITY_GROUP:-sg-default}"
REGION="${AWS_REGION:-us-east-1}"
VOLUME_SIZE_GB=8000                   # 8TB for intermediate files (6TB output + scratch)
VOLUME_IOPS=16000
VOLUME_THROUGHPUT=1000

# Parse arguments
# Default to ON-DEMAND for ~1 hour builds (spot 24hr commitment not worth it)
USE_SPOT=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --on-demand)
            USE_SPOT=false
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --key-name)
            KEY_NAME="$2"
            shift 2
            ;;
        --security-group)
            SECURITY_GROUP="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Build user-data script
USER_DATA=$(cat <<'USERDATA'
#!/bin/bash
set -ex

# Logging
exec > >(tee /var/log/earth_matrix_setup.log) 2>&1
echo "=== Earth Matrix Setup Started: $(date) ==="

# Install dependencies
yum update -y
yum install -y python3.11 python3.11-pip git wget unzip

# Install Python packages
pip3.11 install --upgrade pip
pip3.11 install duckdb h3 pandas pyarrow numpy boto3 tqdm

# Install DuckDB CLI
cd /tmp
wget -q https://github.com/duckdb/duckdb/releases/download/v1.1.3/duckdb_cli-linux-amd64.zip
unzip -o duckdb_cli-linux-amd64.zip -d /usr/local/bin/
chmod +x /usr/local/bin/duckdb

# Create directories
mkdir -p /data/earth_matrix
mkdir -p /tmp/earth_matrix/{hex_fill,water,pois,buildings,matrix}

# Set environment for 384 vCPUs
export PYTHON_WORKERS=380
export DUCKDB_THREADS=50
export DUCKDB_MEMORY="30GB"

# CRITICAL: Memory safety for 384 processes
# Use Arrow IPC for shared memory (not Pandas copy-on-write)
export POLARS_MAX_THREADS=384
export ARROW_DEFAULT_MEMORY_POOL=system

# S3 bucket for output and checkpoints
export S3_BUCKET="${S3_BUCKET:-earth-matrix-output}"

# Clone repository
cd /opt
git clone https://github.com/latintzar/reformia.git || true
cd reformia

# Set up logging
touch /var/log/earth_matrix.log
chmod 666 /var/log/earth_matrix.log

echo "=== Starting Earth Matrix Build: $(date) ==="

# Run the build
cd /opt/reformia
python3.11 backend/etl/build_global_matrix.py 2>&1 | tee -a /var/log/earth_matrix.log

echo "=== Build Complete: $(date) ==="

# Upload results to S3 (if S3_BUCKET is set)
if [ -n "$S3_BUCKET" ]; then
    echo "Uploading to S3..."
    aws s3 sync /data/earth_matrix s3://$S3_BUCKET/earth_matrix/
fi

echo "=== Upload Complete: $(date) ==="

# Self-terminate (optional - uncomment to enable)
# INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
# aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region $REGION

echo "=== Done: $(date) ==="
USERDATA
)

# Encode user-data
USER_DATA_ENCODED=$(echo "$USER_DATA" | base64 -w 0)

# Build instance market options
if [ "$USE_SPOT" = true ]; then
    MARKET_OPTIONS='{"MarketType":"spot","SpotOptions":{"MaxPrice":"7.00","SpotInstanceType":"one-time"}}'
    PRICING="spot (~\$6/hr)"
else
    MARKET_OPTIONS=''
    PRICING="on-demand (~\$20/hr)"
fi

# Build block device mapping
BLOCK_DEVICES="[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":${VOLUME_SIZE_GB},\"VolumeType\":\"gp3\",\"Iops\":${VOLUME_IOPS},\"Throughput\":${VOLUME_THROUGHPUT},\"DeleteOnTermination\":true}}]"

echo "============================================================"
echo "Global Earth Matrix Build Launch (MAXED Schema)"
echo "============================================================"
echo ""
echo "Instance Type:  $INSTANCE_TYPE (384 vCPU, 1.5TB RAM, 100Gbps)"
echo "Pricing:        $PRICING"
echo "Region:         $REGION"
echo "Volume:         ${VOLUME_SIZE_GB}GB gp3 (${VOLUME_IOPS} IOPS)"
echo "Key Pair:       $KEY_NAME"
echo "Security Group: $SECURITY_GROUP"
echo ""
echo "Schema:         ULTRA-MAXED (1,081 Level-3 POIs, 5,745 columns)"
echo "Estimated runtime: ~4.5 hours"
echo "Estimated cost:    ~\$90 on-demand"
echo "Output size:       ~6 TB"
echo ""
echo "Memory-safe: Chunks sequential, categories parallel"
echo "Resume-capable: Checkpoints saved to /tmp/earth_matrix/checkpoint.json"
echo ""
echo "Level-3 Granularity:"
echo "  - italian_restaurant vs japanese_restaurant vs thai_restaurant"
echo "  - wine_bar vs cocktail_bar vs sports_bar"  
echo "  - crossfit vs yoga_studio vs boxing_gym"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would launch instance with above configuration"
    exit 0
fi

read -p "Proceed with launch? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Launching instance..."

# Launch instance
if [ "$USE_SPOT" = true ]; then
    INSTANCE_ID=$(aws ec2 run-instances \
        --image-id "$AMI_ID" \
        --instance-type "$INSTANCE_TYPE" \
        --instance-market-options "$MARKET_OPTIONS" \
        --key-name "$KEY_NAME" \
        --security-group-ids "$SECURITY_GROUP" \
        --block-device-mappings "$BLOCK_DEVICES" \
        --user-data "$USER_DATA_ENCODED" \
        --region "$REGION" \
        --query 'Instances[0].InstanceId' \
        --output text)
else
    INSTANCE_ID=$(aws ec2 run-instances \
        --image-id "$AMI_ID" \
        --instance-type "$INSTANCE_TYPE" \
        --key-name "$KEY_NAME" \
        --security-group-ids "$SECURITY_GROUP" \
        --block-device-mappings "$BLOCK_DEVICES" \
        --user-data "$USER_DATA_ENCODED" \
        --region "$REGION" \
        --query 'Instances[0].InstanceId' \
        --output text)
fi

echo "Instance launched: $INSTANCE_ID"

# Wait for running state
echo "Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo ""
echo "============================================================"
echo "Instance Ready!"
echo "============================================================"
echo ""
echo "Instance ID:  $INSTANCE_ID"
echo "Public IP:    $PUBLIC_IP"
echo ""
echo "To monitor progress:"
echo "  ssh -i ~/.ssh/${KEY_NAME}.pem ec2-user@${PUBLIC_IP}"
echo "  tail -f /var/log/earth_matrix.log"
echo ""
echo "To check status:"
echo "  aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].State.Name'"
echo ""
echo "To terminate:"
echo "  aws ec2 terminate-instances --instance-ids $INSTANCE_ID"
echo ""

