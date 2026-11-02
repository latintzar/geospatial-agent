# Historical cloud build and transfer scripts

These scripts record the original provisioning and transfer design. Instance types, images, account resources, repository paths, runtimes and price estimates are historical source values. The active launch entries print a local plan. Reuse of these records is an owner-commissioned cloud deployment with an account, dataset, query allowance, storage limit and termination deadline. The algorithms and geographic feature-building code remain in `backend/etl/`.

The hosted map uses retained results and local computation. Global matrix completion remains unverified. Start with the [map example](../AGENT-SETUP.md#run-the-map-example) or the local [Retail Location Similarity](https://github.com/latintzar/retail-location-similarity) scorer and original London matrix.

## backend/etl/global/scripts/launch_global_build.sh

Original SHA-256: `469332a72c7884e6550a20614451705bec8348a4213e7cad48e2f9b3a4e578b0`.

```bash
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

```

## backend/scripts/launch_ec2_workers.py

Original SHA-256: `d4b09513aea2181addfce01bec99d65c6ef02ff580c2c37e2d5fbec0f512e111`.

```python
#!/usr/bin/env python3
"""
Launch EC2 Workers for Global Population Processing
====================================================

Spins up multiple EC2 instances to process GHS-POP tiles in parallel,
then uploads results to S3.

Each instance:
1. Installs dependencies
2. Processes its assigned tile range
3. Uploads to S3
4. Self-terminates

Usage:
    python launch_ec2_workers.py --instances 10

Cost estimate:
    - 10 × t3.medium × 10 hours = $4
    - Processing time: ~10 hours
    - S3 storage: ~$2/month
"""

import os
import sys
import json
import time
import argparse
import logging
import base64
import boto3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

# Configuration
AWS_REGION = os.getenv('AWS_REGION', 'us-west-2')
INSTANCE_TYPE = 't3.medium'  # 2 vCPU, 4GB RAM - good for processing
AMI_ID = 'ami-0735c191cf914754d'  # Ubuntu 22.04 LTS (us-west-2)
KEY_NAME = 'puedo-casa-harvest'  # Your SSH key
S3_BUCKET = 'puedo-casa-population'
SECURITY_GROUP = 'sg-0a1b2c3d4e5f6g7h8'  # Update with your SG

# Total tiles
TOTAL_ROWS = 18
TOTAL_COLS = 36
TOTAL_TILES = TOTAL_ROWS * TOTAL_COLS  # 648


def generate_user_data(instance_id: int, start_tile: int, end_tile: int) -> str:
    """
    Generate the startup script for an EC2 instance.
    
    This script runs when the instance starts and:
    1. Installs Python and dependencies
    2. Downloads the processing script
    3. Processes assigned tiles
    4. Uploads to S3
    5. Terminates itself
    """
    script = f"""#!/bin/bash
set -ex

# Log everything
exec > >(tee /var/log/population-worker.log) 2>&1

echo "=========================================="
echo "Population Worker {instance_id}"
echo "Tiles: {start_tile} to {end_tile}"
echo "=========================================="

# Install dependencies
apt-get update
apt-get install -y python3-pip python3-venv awscli

# Create virtual environment
python3 -m venv /opt/population-env
source /opt/population-env/bin/activate

# Install Python packages
pip install --upgrade pip
pip install rasterio h3 pandas pyarrow numpy tqdm requests boto3

# Create working directory
mkdir -p /opt/population-work
cd /opt/population-work

# Download the processing script from S3 (or embed it)
cat > process_tiles.py << 'PYTHON_SCRIPT'
import os
import sys
import zipfile
import requests
import numpy as np
import pandas as pd
import h3
import boto3
from pathlib import Path
from tqdm import tqdm
import rasterio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GHS_TILES_BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2025_GLOBE_R2023A_4326_3ss/V1-0/tiles"
H3_RESOLUTION = 10
S3_BUCKET = "{S3_BUCKET}"
CACHE_DIR = Path("/tmp/ghs_cache")
OUTPUT_DIR = Path("/tmp/population_output")

CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

def tile_index_to_row_col(tile_index):
    row = (tile_index // 36) + 1
    col = (tile_index % 36) + 1
    return row, col

def download_tile(row, col):
    tile_name = f"GHS_POP_E2025_GLOBE_R2023A_4326_3ss_V1_0_R{{row}}_C{{col}}"
    tif_path = CACHE_DIR / f"{{tile_name}}.tif"
    
    if tif_path.exists():
        return tif_path
    
    zip_url = f"{{GHS_TILES_BASE}}/{{tile_name}}.zip"
    zip_path = CACHE_DIR / f"{{tile_name}}.zip"
    
    try:
        response = requests.get(zip_url, stream=True, timeout=120)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(8192):
                f.write(chunk)
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            tif_files = [f for f in zf.namelist() if f.endswith('.tif')]
            if tif_files:
                zf.extract(tif_files[0], CACHE_DIR)
                extracted = CACHE_DIR / tif_files[0]
                if extracted != tif_path:
                    extracted.rename(tif_path)
        
        zip_path.unlink()
        return tif_path
    except Exception as e:
        logger.warning(f"Failed R{{row}}_C{{col}}: {{e}}")
        return None

def process_tile(tif_path, row, col):
    h3_data = {{}}
    
    with rasterio.open(tif_path) as src:
        data = src.read(1)
        transform = src.transform
        rows_px, cols_px = data.shape
        
        for r in range(rows_px):
            for c in range(cols_px):
                pop_value = data[r, c]
                if pop_value <= 0 or np.isnan(pop_value):
                    continue
                lon, lat = rasterio.transform.xy(transform, r, c)
                hex_id = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
                h3_data[hex_id] = h3_data.get(hex_id, 0) + pop_value
    
    if not h3_data:
        return None
    
    records = []
    for hex_id, pop in h3_data.items():
        lat, lng = h3.cell_to_latlng(hex_id)
        records.append({{
            'hex': hex_id,
            'population': int(round(pop)),
            'lat': round(lat, 6),
            'lng': round(lng, 6)
        }})
    
    return pd.DataFrame(records)

def save_and_upload(df, row, col):
    if df is None or df.empty:
        return
    
    df['h3_prefix'] = df['hex'].str[:3]
    s3 = boto3.client('s3')
    
    for prefix, group in df.groupby('h3_prefix'):
        local_path = OUTPUT_DIR / prefix / f"R{{row}}_C{{col}}.parquet"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        group.drop(columns=['h3_prefix']).to_parquet(local_path, index=False)
        
        s3_key = f"h3_res10/{{prefix}}/R{{row}}_C{{col}}.parquet"
        s3.upload_file(str(local_path), S3_BUCKET, s3_key)
        local_path.unlink()

def main():
    start_tile = {start_tile}
    end_tile = {end_tile}
    
    logger.info(f"Processing tiles {{start_tile}} to {{end_tile}}")
    
    for tile_idx in range(start_tile, end_tile + 1):
        row, col = tile_index_to_row_col(tile_idx)
        logger.info(f"Processing R{{row}}_C{{col}} (tile {{tile_idx}})")
        
        tif_path = download_tile(row, col)
        if tif_path is None:
            logger.info(f"  Skipped (not found)")
            continue
        
        df = process_tile(tif_path, row, col)
        save_and_upload(df, row, col)
        
        # Clean up to save disk space
        tif_path.unlink()
        logger.info(f"  Done")
    
    logger.info("All tiles processed!")

if __name__ == "__main__":
    main()
PYTHON_SCRIPT

# Run the processing
python3 process_tiles.py

echo "=========================================="
echo "Worker {instance_id} COMPLETE"
echo "=========================================="

# Self-terminate
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region {AWS_REGION}
"""
    return base64.b64encode(script.encode()).decode()


def launch_workers(num_instances: int, dry_run: bool = False):
    """Launch EC2 instances to process tiles in parallel."""
    
    logger.info(f"🚀 Launching {num_instances} EC2 workers...")
    
    # Calculate tile ranges
    tiles_per_instance = TOTAL_TILES // num_instances
    
    ec2 = boto3.client('ec2', region_name=AWS_REGION)
    
    instances = []
    
    for i in range(num_instances):
        start_tile = i * tiles_per_instance
        end_tile = start_tile + tiles_per_instance - 1
        
        # Last instance gets any remaining tiles
        if i == num_instances - 1:
            end_tile = TOTAL_TILES - 1
        
        logger.info(f"  Worker {i+1}: tiles {start_tile}-{end_tile}")
        
        if dry_run:
            continue
        
        user_data = generate_user_data(i + 1, start_tile, end_tile)
        
        response = ec2.run_instances(
            ImageId=AMI_ID,
            InstanceType=INSTANCE_TYPE,
            KeyName=KEY_NAME,
            MinCount=1,
            MaxCount=1,
            UserData=user_data,
            IamInstanceProfile={'Name': 'EC2-S3-Access'},  # Need S3 write access
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': [
                    {'Key': 'Name', 'Value': f'population-worker-{i+1}'},
                    {'Key': 'Project', 'Value': 'puedo-casa'},
                    {'Key': 'Purpose', 'Value': 'population-precompute'},
                ]
            }],
            InstanceInitiatedShutdownBehavior='terminate',
        )
        
        instance_id = response['Instances'][0]['InstanceId']
        instances.append(instance_id)
        logger.info(f"    Launched: {instance_id}")
    
    if not dry_run:
        logger.info(f"\n✅ Launched {len(instances)} instances")
        logger.info(f"   Monitor: aws ec2 describe-instances --instance-ids {' '.join(instances)}")
        logger.info(f"   S3 progress: aws s3 ls s3://{S3_BUCKET}/h3_res10/ --summarize")


def main():
    parser = argparse.ArgumentParser(description="Launch EC2 workers for population processing")
    parser.add_argument('--instances', type=int, default=10, help="Number of EC2 instances")
    parser.add_argument('--dry-run', action='store_true', help="Show plan without launching")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🌍 Global Population Processing - EC2 Workers")
    print("=" * 60)
    print(f"Instances: {args.instances}")
    print(f"Total tiles: {TOTAL_TILES}")
    print(f"Tiles per instance: ~{TOTAL_TILES // args.instances}")
    print(f"Estimated time: ~{100 // args.instances} hours")
    print(f"Estimated cost: ~${args.instances * 0.04 * (100 / args.instances):.2f}")
    print("=" * 60)
    
    if args.dry_run:
        print("\n[DRY RUN - no instances will be launched]\n")
    
    launch_workers(args.instances, args.dry_run)


if __name__ == "__main__":
    main()

```

## backend/scripts/launch_matrix_build.sh

Original SHA-256: `f731e4de85e36e083840e063fa282034b28fd6d0df75b15eb9e46df01a6c87b7`.

```bash
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
```

## backend/scripts/launch_matrix_builder.sh

Original SHA-256: `4ff5caddef3e3e2bc378b3cecb845c19d868a9bd9df795c8da9496f0bcfc29bf`.

```bash
#!/bin/bash
# =============================================================================
# Earth Matrix Builder - EC2 Launcher
# =============================================================================
# Launches r7i.metal-48xl spot instance to build the global Earth Matrix
#
# Cost: ~$1.27/hour spot (us-east-1a) vs $12.70/hour on-demand
# Expected time: 1-3 hours for global build
# Total cost: ~$2-5
#
# Usage:
#   ./launch_matrix_builder.sh [--on-demand]
# =============================================================================

set -e

# Configuration
INSTANCE_TYPE="r7i.metal-48xl"
AMI_ID="ami-0c7217cdde317cfec"  # Ubuntu 22.04 LTS us-east-1
KEY_NAME="matrix-builder"
SECURITY_GROUP="matrix-builder-sg"
REGION="us-east-1"
AZ="us-east-1a"  # Cheapest spot zone

# Check for on-demand flag
USE_SPOT=true
if [[ "$1" == "--on-demand" ]]; then
    USE_SPOT=false
    echo "⚠️  Using ON-DEMAND pricing ($12.70/hour)"
else
    echo "💰 Using SPOT pricing (~$1.27/hour in $AZ)"
fi

echo "============================================================"
echo "🚀 EARTH MATRIX BUILDER - EC2 LAUNCHER"
echo "============================================================"
echo "Instance: $INSTANCE_TYPE (192 vCPUs, 1.5TB RAM)"
echo "Region:   $REGION ($AZ)"
echo "AMI:      $AMI_ID (Ubuntu 22.04)"
echo "============================================================"

# Load credentials from .env.local
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../../.env.local"

if [[ -f "$ENV_FILE" ]]; then
    export AWS_ACCESS_KEY_ID=$(grep AWS_ACCESS_KEY_ID "$ENV_FILE" | cut -d'=' -f2)
    export AWS_SECRET_ACCESS_KEY=$(grep AWS_SECRET_ACCESS_KEY "$ENV_FILE" | cut -d'=' -f2)
    export AWS_DEFAULT_REGION=$REGION
    echo "✅ Loaded AWS credentials from .env.local"
else
    echo "❌ .env.local not found at $ENV_FILE"
    exit 1
fi

# Create key pair if doesn't exist
echo ""
echo "🔑 Checking SSH key pair..."
if ! aws ec2 describe-key-pairs --key-names "$KEY_NAME" &>/dev/null; then
    echo "   Creating new key pair: $KEY_NAME"
    aws ec2 create-key-pair --key-name "$KEY_NAME" --query 'KeyMaterial' --output text > ~/.ssh/${KEY_NAME}.pem
    chmod 600 ~/.ssh/${KEY_NAME}.pem
    echo "   ✅ Key saved to ~/.ssh/${KEY_NAME}.pem"
else
    echo "   ✅ Key pair exists"
fi

# Create security group if doesn't exist
echo ""
echo "🔒 Checking security group..."
SG_ID=$(aws ec2 describe-security-groups --group-names "$SECURITY_GROUP" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "")

if [[ -z "$SG_ID" || "$SG_ID" == "None" ]]; then
    echo "   Creating security group: $SECURITY_GROUP"
    SG_ID=$(aws ec2 create-security-group \
        --group-name "$SECURITY_GROUP" \
        --description "Earth Matrix Builder - SSH access" \
        --query 'GroupId' --output text)
    
    # Allow SSH from anywhere (you may want to restrict this)
    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_ID" \
        --protocol tcp \
        --port 22 \
        --cidr 0.0.0.0/0
    echo "   ✅ Security group created: $SG_ID"
else
    echo "   ✅ Security group exists: $SG_ID"
fi

# User data script to install dependencies and run the build
USER_DATA=$(cat << 'USERDATA'
#!/bin/bash
set -ex

# Log everything
exec > >(tee /var/log/matrix-builder.log) 2>&1
echo "=== Matrix Builder Starting at $(date) ==="

# Update system
apt-get update
apt-get install -y python3-pip python3-venv git htop

# Create working directory
mkdir -p /home/ubuntu/matrix-builder
cd /home/ubuntu/matrix-builder

# Clone or create the ETL script
cat > build_earth_matrix.py << 'PYTHON'
#!/usr/bin/env python3
"""
Earth Matrix Builder - Minimal version for EC2
"""
import duckdb
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

H3_RESOLUTION = 9
OVERTURE_S3_BASE = "s3://overturemaps-us-west-2/release/2025-12-17.0"
OUTPUT_DIR = Path("/home/ubuntu/matrix-builder/output")
OUTPUT_DIR.mkdir(exist_ok=True)

def main():
    start = time.time()
    logger.info("🌍 EARTH MATRIX BUILDER - Starting global build")
    logger.info(f"Instance: r7i.metal-48xl (192 vCPUs, 1.5TB RAM)")
    
    con = duckdb.connect()
    con.execute("SET threads TO 192;")  # Use all cores
    con.execute("SET memory_limit = '1400GB';")  # Use most of RAM
    
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL h3 FROM community; LOAD h3;")
    con.execute("SET s3_region='us-west-2';")
    
    logger.info("✅ DuckDB initialized with 192 threads, 1.4TB RAM")
    
    # Step 1: Places
    logger.info("📍 Processing PLACES...")
    t0 = time.time()
    con.execute(f"""
        CREATE TABLE places_h3 AS
        SELECT
            h3_latlng_to_cell(ST_Y(ST_Centroid(geometry)), ST_X(ST_Centroid(geometry)), {H3_RESOLUTION}) as h3_index,
            COUNT(*) as total_places,
            COUNT(CASE WHEN categories.primary = 'cafe' THEN 1 END) as cafe_count,
            COUNT(CASE WHEN categories.primary = 'restaurant' THEN 1 END) as restaurant_count,
            COUNT(CASE WHEN categories.primary = 'hospital' THEN 1 END) as hospital_count,
            COUNT(CASE WHEN categories.primary = 'school' THEN 1 END) as school_count
        FROM read_parquet('{OVERTURE_S3_BASE}/theme=places/type=place/*', hive_partitioning=true)
        WHERE geometry IS NOT NULL
        GROUP BY 1
    """)
    places_count = con.execute("SELECT COUNT(*) FROM places_h3").fetchone()[0]
    logger.info(f"   ✅ Places: {places_count:,} hexes ({time.time()-t0:.1f}s)")
    
    # Step 2: Buildings (THE BIG ONE)
    logger.info("🏢 Processing BUILDINGS (2B+ rows)...")
    t0 = time.time()
    con.execute(f"""
        CREATE TABLE buildings_h3 AS
        SELECT
            h3_latlng_to_cell(ST_Y(ST_Centroid(geometry)), ST_X(ST_Centroid(geometry)), {H3_RESOLUTION}) as h3_index,
            COUNT(*) as building_density,
            AVG(COALESCE(height, 10)) as avg_building_height
        FROM read_parquet('{OVERTURE_S3_BASE}/theme=buildings/type=building/*', hive_partitioning=true)
        WHERE geometry IS NOT NULL
        GROUP BY 1
    """)
    buildings_count = con.execute("SELECT COUNT(*) FROM buildings_h3").fetchone()[0]
    total_buildings = con.execute("SELECT SUM(building_density) FROM buildings_h3").fetchone()[0]
    logger.info(f"   ✅ Buildings: {buildings_count:,} hexes, {total_buildings:,.0f} buildings ({time.time()-t0:.1f}s)")
    
    # Step 3: Land Use
    logger.info("🌳 Processing LAND USE...")
    t0 = time.time()
    con.execute(f"""
        CREATE TABLE land_use_h3 AS
        SELECT
            h3_latlng_to_cell(ST_Y(ST_Centroid(geometry)), ST_X(ST_Centroid(geometry)), {H3_RESOLUTION}) as h3_index,
            MAX(CASE WHEN class = 'park' THEN 1 ELSE 0 END) as has_park,
            MAX(CASE WHEN class = 'forest' THEN 1 ELSE 0 END) as has_forest,
            MAX(CASE WHEN class = 'residential' THEN 1 ELSE 0 END) as has_residential,
            MAX(CASE WHEN class = 'commercial' THEN 1 ELSE 0 END) as has_commercial
        FROM read_parquet('{OVERTURE_S3_BASE}/theme=base/type=land_use/*', hive_partitioning=true)
        WHERE geometry IS NOT NULL
        GROUP BY 1
    """)
    landuse_count = con.execute("SELECT COUNT(*) FROM land_use_h3").fetchone()[0]
    logger.info(f"   ✅ Land Use: {landuse_count:,} hexes ({time.time()-t0:.1f}s)")
    
    # Step 4: Merge
    logger.info("🔗 Merging all tables...")
    t0 = time.time()
    con.execute("""
        CREATE TABLE earth_matrix AS
        SELECT
            COALESCE(p.h3_index, b.h3_index, l.h3_index) as h3_index,
            COALESCE(p.total_places, 0) as total_places,
            COALESCE(p.cafe_count, 0) as cafe_count,
            COALESCE(p.restaurant_count, 0) as restaurant_count,
            COALESCE(p.hospital_count, 0) as hospital_count,
            COALESCE(p.school_count, 0) as school_count,
            COALESCE(b.building_density, 0) as building_density,
            COALESCE(b.avg_building_height, 10) as avg_building_height,
            COALESCE(l.has_park, 0) as has_park,
            COALESCE(l.has_forest, 0) as has_forest,
            COALESCE(l.has_residential, 0) as has_residential,
            COALESCE(l.has_commercial, 0) as has_commercial
        FROM places_h3 p
        FULL OUTER JOIN buildings_h3 b ON p.h3_index = b.h3_index
        FULL OUTER JOIN land_use_h3 l ON COALESCE(p.h3_index, b.h3_index) = l.h3_index
    """)
    matrix_count = con.execute("SELECT COUNT(*) FROM earth_matrix").fetchone()[0]
    logger.info(f"   ✅ Merged: {matrix_count:,} hexes ({time.time()-t0:.1f}s)")
    
    # Step 5: Write output
    output_path = OUTPUT_DIR / "earth_matrix_global.parquet"
    logger.info(f"💾 Writing to {output_path}...")
    con.execute(f"COPY earth_matrix TO '{output_path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    
    size_mb = output_path.stat().st_size / (1024 * 1024)
    elapsed = time.time() - start
    
    logger.info("=" * 60)
    logger.info("✅ BUILD COMPLETE")
    logger.info(f"   Duration: {elapsed/60:.1f} minutes")
    logger.info(f"   Output: {output_path}")
    logger.info(f"   Size: {size_mb:.2f} MB")
    logger.info(f"   Hexes: {matrix_count:,}")
    logger.info("=" * 60)
    
    # Signal completion
    Path("/home/ubuntu/matrix-builder/COMPLETE").write_text(f"Done in {elapsed/60:.1f} min, {matrix_count:,} hexes")

if __name__ == "__main__":
    main()
PYTHON

# Install DuckDB
pip3 install duckdb

# Run the build
echo "=== Starting Matrix Build at $(date) ==="
python3 build_earth_matrix.py

echo "=== Matrix Builder Complete at $(date) ==="
USERDATA
)

# Launch the instance
echo ""
echo "🚀 Launching EC2 instance..."

if $USE_SPOT; then
    # Spot instance
    INSTANCE_ID=$(aws ec2 run-instances \
        --image-id "$AMI_ID" \
        --instance-type "$INSTANCE_TYPE" \
        --key-name "$KEY_NAME" \
        --security-group-ids "$SG_ID" \
        --placement "AvailabilityZone=$AZ" \
        --instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=one-time}' \
        --user-data "$USER_DATA" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=matrix-builder}]" \
        --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":500,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
        --query 'Instances[0].InstanceId' \
        --output text)
else
    # On-demand instance
    INSTANCE_ID=$(aws ec2 run-instances \
        --image-id "$AMI_ID" \
        --instance-type "$INSTANCE_TYPE" \
        --key-name "$KEY_NAME" \
        --security-group-ids "$SG_ID" \
        --placement "AvailabilityZone=$AZ" \
        --user-data "$USER_DATA" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=matrix-builder}]" \
        --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":500,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
        --query 'Instances[0].InstanceId' \
        --output text)
fi

echo "   ✅ Instance launched: $INSTANCE_ID"

# Wait for running
echo ""
echo "⏳ Waiting for instance to start..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo ""
echo "============================================================"
echo "✅ INSTANCE READY"
echo "============================================================"
echo "Instance ID: $INSTANCE_ID"
echo "Public IP:   $PUBLIC_IP"
echo "SSH:         ssh -i ~/.ssh/${KEY_NAME}.pem ubuntu@$PUBLIC_IP"
echo ""
echo "Monitor build:"
echo "  ssh -i ~/.ssh/${KEY_NAME}.pem ubuntu@$PUBLIC_IP 'tail -f /var/log/matrix-builder.log'"
echo ""
echo "Check completion:"
echo "  ssh -i ~/.ssh/${KEY_NAME}.pem ubuntu@$PUBLIC_IP 'cat /home/ubuntu/matrix-builder/COMPLETE 2>/dev/null || echo \"Still running...\"'"
echo ""
echo "Download result:"
echo "  scp -i ~/.ssh/${KEY_NAME}.pem ubuntu@$PUBLIC_IP:/home/ubuntu/matrix-builder/output/earth_matrix_global.parquet ."
echo ""
echo "TERMINATE when done (to stop charges):"
echo "  aws ec2 terminate-instances --instance-ids $INSTANCE_ID"
echo ""
echo "💰 Estimated cost: ~\$1.27/hour (spot in $AZ)"
echo "============================================================"
```

## scripts/launch_london_build.sh

Original SHA-256: `3c5922ed100763844903cd10df2b803559bbe26808581b9edfe627432428ae7e`.

```bash
#!/bin/bash
# =============================================================================
# LONDON EARTH MATRIX BUILD - EC2 Launch Script
# Instance: m8i.96xlarge (384 vCPU, 1.5TB RAM)
# =============================================================================

set -e

# Configuration
INSTANCE_TYPE="m8i.96xlarge"
AMI_ID="ami-08d7aabbb50c2c24e"  # Amazon Linux 2023 (has Python 3.11)
KEY_NAME="matrix-builder"
SECURITY_GROUP="sg-07c6ca4e8bbcd8139"  # matrix-builder-sg
REGION="us-east-1"

# London bounding box
LONDON_BBOX="-0.5103,51.2868,0.3340,51.6919"

# User data script (base64 encoded)
USER_DATA=$(cat << 'USERDATA' | base64
#!/bin/bash
exec > /var/log/matrix-build.log 2>&1
set -ex

echo "=========================================="
echo "LONDON EARTH MATRIX BUILD - $(date)"
echo "=========================================="

# System info
echo "Instance type: $(curl -s http://169.254.169.254/latest/meta-data/instance-type)"
echo "CPUs: $(nproc)"
echo "Memory: $(free -h | grep Mem | awk '{print $2}')"

# Install dependencies (Amazon Linux 2023)
dnf update -y
dnf install -y python3.11 python3.11-pip git htop tmux gcc python3.11-devel

# Install Python packages
python3.11 -m pip install --upgrade pip
python3.11 -m pip install duckdb pandas pyarrow h3 shapely requests tqdm

# Clone repository
cd /home/ec2-user
git clone https://github.com/latintzar/Leo.git
cd Leo

# Create output directory
mkdir -p /home/ec2-user/output/earth_matrix_london

# Set environment
export PYTHONPATH=/home/ec2-user/Leo

# London bounding box
BBOX="-0.5103,51.2868,0.3340,51.6919"

echo "=========================================="
echo "STARTING BUILD - $(date)"
echo "Bounding Box: $BBOX"
echo "=========================================="

# Run the build with performance logging
cd /home/ec2-user/Leo/backend/etl/global

python3.11 << 'PYTHON'
import os
import sys
import time
import json
import logging
from datetime import datetime

# Add project to path
sys.path.insert(0, '/home/ec2-user/Leo')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('/var/log/matrix-build-detailed.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# Performance tracking
perf_log = {
    "start_time": datetime.now().isoformat(),
    "bbox": "-0.5103,51.2868,0.3340,51.6919",
    "area_name": "London",
    "phases": {}
}

def log_phase(name, start_time):
    elapsed = time.time() - start_time
    perf_log["phases"][name] = {
        "duration_seconds": elapsed,
        "duration_human": f"{elapsed/60:.1f} minutes"
    }
    log.info(f"Phase '{name}' completed in {elapsed:.1f}s ({elapsed/60:.1f} min)")

try:
    from build_global_matrix import (
        load_overture_places,
        load_overture_land_use,
        load_overture_water,
        load_overture_coastlines,
        load_overture_transit,
        load_overture_roads,
        build_resolution,
        aggregate_to_res5,
        RESOLUTIONS,
        OUTPUT_DIR,
        FINAL_OUTPUT
    )
    import duckdb
    
    # London bbox
    BBOX = [-0.5103, 51.2868, 0.3340, 51.6919]
    AREA_NAME = "London"
    
    # Override output dir
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_OUTPUT.mkdir(parents=True, exist_ok=True)
    
    log.info("=" * 70)
    log.info("LONDON EARTH MATRIX BUILD")
    log.info("=" * 70)
    log.info(f"Bounding Box: {BBOX}")
    log.info(f"Resolutions: {RESOLUTIONS}")
    log.info(f"Output: {FINAL_OUTPUT}")
    
    # Phase 1: Load Overture Data
    log.info("\n" + "=" * 70)
    log.info("PHASE 1: Loading Overture Data")
    log.info("=" * 70)
    
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("SET s3_region='us-west-2';")
    
    phase_start = time.time()
    
    # Load all data types
    log.info("Loading Places...")
    t0 = time.time()
    places = load_overture_places(con, BBOX, AREA_NAME)
    log.info(f"  Places loaded: {len(places) if places is not None else 0} rows in {time.time()-t0:.1f}s")
    
    log.info("Loading Land Use...")
    t0 = time.time()
    land_use = load_overture_land_use(con, BBOX, AREA_NAME)
    log.info(f"  Land Use loaded: {len(land_use) if land_use is not None else 0} rows in {time.time()-t0:.1f}s")
    
    log.info("Loading Water...")
    t0 = time.time()
    water = load_overture_water(con, BBOX, AREA_NAME)
    log.info(f"  Water loaded: {len(water) if water is not None else 0} rows in {time.time()-t0:.1f}s")
    
    log.info("Loading Transit...")
    t0 = time.time()
    transit = load_overture_transit(con, BBOX, AREA_NAME)
    log.info(f"  Transit loaded: {len(transit) if transit is not None else 0} rows in {time.time()-t0:.1f}s")
    
    log.info("Loading Roads...")
    t0 = time.time()
    roads = load_overture_roads(con, BBOX, AREA_NAME)
    log.info(f"  Roads loaded: {len(roads) if roads is not None else 0} rows in {time.time()-t0:.1f}s")
    
    log_phase("data_loading", phase_start)
    
    # Phase 2: Build each resolution
    log.info("\n" + "=" * 70)
    log.info("PHASE 2: Building Resolutions")
    log.info("=" * 70)
    
    for resolution in RESOLUTIONS:
        log.info(f"\n--- Resolution {resolution} ---")
        phase_start = time.time()
        
        df = build_resolution(
            con=con,
            resolution=resolution,
            places=places,
            land_use=land_use,
            water=water,
            coastlines=None,
            transit=transit,
            roads=roads,
            area_name=AREA_NAME
        )
        
        if df is not None and not df.empty:
            output_path = FINAL_OUTPUT / f"earth_matrix_london_res{resolution}.parquet"
            df.to_parquet(output_path, compression='zstd')
            
            perf_log["phases"][f"res{resolution}"] = {
                "duration_seconds": time.time() - phase_start,
                "rows": len(df),
                "columns": len(df.columns),
                "file_size_mb": output_path.stat().st_size / (1024*1024)
            }
            
            log.info(f"  Rows: {len(df):,}")
            log.info(f"  Columns: {len(df.columns):,}")
            log.info(f"  File size: {output_path.stat().st_size / (1024*1024):.1f} MB")
            log.info(f"  Duration: {time.time() - phase_start:.1f}s")
        else:
            log.warning(f"  No data for resolution {resolution}")
    
    # Phase 3: Aggregate to Res 5
    log.info("\n" + "=" * 70)
    log.info("PHASE 3: Aggregating to Res 5")
    log.info("=" * 70)
    
    phase_start = time.time()
    res8_path = FINAL_OUTPUT / "earth_matrix_london_res8.parquet"
    if res8_path.exists():
        import pandas as pd
        res8 = pd.read_parquet(res8_path)
        res5 = aggregate_to_res5(res8)
        
        if res5 is not None and not res5.empty:
            output_path = FINAL_OUTPUT / "earth_matrix_london_res5.parquet"
            res5.to_parquet(output_path, compression='zstd')
            
            perf_log["phases"]["res5_aggregation"] = {
                "duration_seconds": time.time() - phase_start,
                "rows": len(res5),
                "columns": len(res5.columns),
                "file_size_mb": output_path.stat().st_size / (1024*1024)
            }
            
            log.info(f"  Rows: {len(res5):,}")
            log.info(f"  Columns: {len(res5.columns):,}")
            log.info(f"  File size: {output_path.stat().st_size / (1024*1024):.1f} MB")
    
    log_phase("res5_aggregation", phase_start)
    
    # Save performance log
    perf_log["end_time"] = datetime.now().isoformat()
    perf_log["total_duration_seconds"] = sum(
        p.get("duration_seconds", 0) for p in perf_log["phases"].values()
    )
    
    with open(FINAL_OUTPUT / "performance_log.json", "w") as f:
        json.dump(perf_log, f, indent=2)
    
    log.info("\n" + "=" * 70)
    log.info("BUILD COMPLETE!")
    log.info("=" * 70)
    log.info(f"Total duration: {perf_log['total_duration_seconds']/60:.1f} minutes")
    log.info(f"Output directory: {FINAL_OUTPUT}")
    
    # List output files
    for f in sorted(FINAL_OUTPUT.glob("*.parquet")):
        log.info(f"  {f.name}: {f.stat().st_size / (1024*1024):.1f} MB")

except Exception as e:
    log.error(f"BUILD FAILED: {e}")
    import traceback
    traceback.print_exc()
    perf_log["error"] = str(e)
    with open("/home/ec2-user/output/performance_log_error.json", "w") as f:
        json.dump(perf_log, f, indent=2)
    raise

PYTHON

echo "=========================================="
echo "BUILD FINISHED - $(date)"
echo "=========================================="

# List output files
ls -lah /home/ec2-user/Leo/output/earth_matrix/

echo "Performance log:"
cat /home/ec2-user/Leo/output/earth_matrix/performance_log.json

USERDATA
)

echo "Launching EC2 instance..."
echo "Instance Type: $INSTANCE_TYPE"
echo "Region: $REGION"
echo "Estimated cost: ~$18/hour"

# Launch instance
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id $AMI_ID \
  --instance-type $INSTANCE_TYPE \
  --key-name $KEY_NAME \
  --security-group-ids $SECURITY_GROUP \
  --user-data "$USER_DATA" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=london-matrix-build},{Key=Project,Value=Leo}]" \
  --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":500,\"VolumeType\":\"gp3\",\"Iops\":16000,\"Throughput\":1000}}]" \
  --query 'Instances[0].InstanceId' \
  --output text)

echo ""
echo "Instance launched: $INSTANCE_ID"
echo ""

# Wait for instance to be running
echo "Waiting for instance to start..."
aws ec2 wait instance-running --instance-ids $INSTANCE_ID

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

echo ""
echo "=========================================="
echo "INSTANCE READY"
echo "=========================================="
echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo ""
echo "SSH Command:"
echo "  ssh -i ~/.ssh/matrix-builder.pem ec2-user@$PUBLIC_IP"
echo ""
echo "Monitor build:"
echo "  ssh -i ~/.ssh/matrix-builder.pem ec2-user@$PUBLIC_IP 'tail -f /var/log/matrix-build.log'"
echo ""
echo "Download results when done:"
echo "  scp -i ~/.ssh/matrix-builder.pem -r ec2-user@$PUBLIC_IP:/home/ec2-user/Leo/output/earth_matrix/*.parquet ."
echo ""
echo "Terminate when done:"
echo "  aws ec2 terminate-instances --instance-ids $INSTANCE_ID"
echo ""


# LONDON EARTH MATRIX BUILD - EC2 Launch Script
# Instance: m8i.96xlarge (384 vCPU, 1.5TB RAM)
# =============================================================================

set -e

# Configuration
INSTANCE_TYPE="m8i.96xlarge"
AMI_ID="ami-08d7aabbb50c2c24e"  # Amazon Linux 2023 (has Python 3.11)
KEY_NAME="matrix-builder"
SECURITY_GROUP="sg-07c6ca4e8bbcd8139"  # matrix-builder-sg
REGION="us-east-1"

# London bounding box
LONDON_BBOX="-0.5103,51.2868,0.3340,51.6919"

# User data script (base64 encoded)
USER_DATA=$(cat << 'USERDATA' | base64
#!/bin/bash
exec > /var/log/matrix-build.log 2>&1
set -ex

echo "=========================================="
echo "LONDON EARTH MATRIX BUILD - $(date)"
echo "=========================================="

# System info
echo "Instance type: $(curl -s http://169.254.169.254/latest/meta-data/instance-type)"
echo "CPUs: $(nproc)"
echo "Memory: $(free -h | grep Mem | awk '{print $2}')"

# Install dependencies (Amazon Linux 2023)
dnf update -y
dnf install -y python3.11 python3.11-pip git htop tmux gcc python3.11-devel

# Install Python packages
python3.11 -m pip install --upgrade pip
python3.11 -m pip install duckdb pandas pyarrow h3 shapely requests tqdm

# Clone repository
cd /home/ec2-user
git clone https://github.com/latintzar/Leo.git
cd Leo

# Create output directory
mkdir -p /home/ec2-user/output/earth_matrix_london

# Set environment
export PYTHONPATH=/home/ec2-user/Leo

# London bounding box
BBOX="-0.5103,51.2868,0.3340,51.6919"

echo "=========================================="
echo "STARTING BUILD - $(date)"
echo "Bounding Box: $BBOX"
echo "=========================================="

# Run the build with performance logging
cd /home/ec2-user/Leo/backend/etl/global

python3.11 << 'PYTHON'
import os
import sys
import time
import json
import logging
from datetime import datetime

# Add project to path
sys.path.insert(0, '/home/ec2-user/Leo')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('/var/log/matrix-build-detailed.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# Performance tracking
perf_log = {
    "start_time": datetime.now().isoformat(),
    "bbox": "-0.5103,51.2868,0.3340,51.6919",
    "area_name": "London",
    "phases": {}
}

def log_phase(name, start_time):
    elapsed = time.time() - start_time
    perf_log["phases"][name] = {
        "duration_seconds": elapsed,
        "duration_human": f"{elapsed/60:.1f} minutes"
    }
    log.info(f"Phase '{name}' completed in {elapsed:.1f}s ({elapsed/60:.1f} min)")

try:
    from build_global_matrix import (
        load_overture_places,
        load_overture_land_use,
        load_overture_water,
        load_overture_coastlines,
        load_overture_transit,
        load_overture_roads,
        build_resolution,
        aggregate_to_res5,
        RESOLUTIONS,
        OUTPUT_DIR,
        FINAL_OUTPUT
    )
    import duckdb
    
    # London bbox
    BBOX = [-0.5103, 51.2868, 0.3340, 51.6919]
    AREA_NAME = "London"
    
    # Override output dir
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_OUTPUT.mkdir(parents=True, exist_ok=True)
    
    log.info("=" * 70)
    log.info("LONDON EARTH MATRIX BUILD")
    log.info("=" * 70)
    log.info(f"Bounding Box: {BBOX}")
    log.info(f"Resolutions: {RESOLUTIONS}")
    log.info(f"Output: {FINAL_OUTPUT}")
    
    # Phase 1: Load Overture Data
    log.info("\n" + "=" * 70)
    log.info("PHASE 1: Loading Overture Data")
    log.info("=" * 70)
    
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("SET s3_region='us-west-2';")
    
    phase_start = time.time()
    
    # Load all data types
    log.info("Loading Places...")
    t0 = time.time()
    places = load_overture_places(con, BBOX, AREA_NAME)
    log.info(f"  Places loaded: {len(places) if places is not None else 0} rows in {time.time()-t0:.1f}s")
    
    log.info("Loading Land Use...")
    t0 = time.time()
    land_use = load_overture_land_use(con, BBOX, AREA_NAME)
    log.info(f"  Land Use loaded: {len(land_use) if land_use is not None else 0} rows in {time.time()-t0:.1f}s")
    
    log.info("Loading Water...")
    t0 = time.time()
    water = load_overture_water(con, BBOX, AREA_NAME)
    log.info(f"  Water loaded: {len(water) if water is not None else 0} rows in {time.time()-t0:.1f}s")
    
    log.info("Loading Transit...")
    t0 = time.time()
    transit = load_overture_transit(con, BBOX, AREA_NAME)
    log.info(f"  Transit loaded: {len(transit) if transit is not None else 0} rows in {time.time()-t0:.1f}s")
    
    log.info("Loading Roads...")
    t0 = time.time()
    roads = load_overture_roads(con, BBOX, AREA_NAME)
    log.info(f"  Roads loaded: {len(roads) if roads is not None else 0} rows in {time.time()-t0:.1f}s")
    
    log_phase("data_loading", phase_start)
    
    # Phase 2: Build each resolution
    log.info("\n" + "=" * 70)
    log.info("PHASE 2: Building Resolutions")
    log.info("=" * 70)
    
    for resolution in RESOLUTIONS:
        log.info(f"\n--- Resolution {resolution} ---")
        phase_start = time.time()
        
        df = build_resolution(
            con=con,
            resolution=resolution,
            places=places,
            land_use=land_use,
            water=water,
            coastlines=None,
            transit=transit,
            roads=roads,
            area_name=AREA_NAME
        )
        
        if df is not None and not df.empty:
            output_path = FINAL_OUTPUT / f"earth_matrix_london_res{resolution}.parquet"
            df.to_parquet(output_path, compression='zstd')
            
            perf_log["phases"][f"res{resolution}"] = {
                "duration_seconds": time.time() - phase_start,
                "rows": len(df),
                "columns": len(df.columns),
                "file_size_mb": output_path.stat().st_size / (1024*1024)
            }
            
            log.info(f"  Rows: {len(df):,}")
            log.info(f"  Columns: {len(df.columns):,}")
            log.info(f"  File size: {output_path.stat().st_size / (1024*1024):.1f} MB")
            log.info(f"  Duration: {time.time() - phase_start:.1f}s")
        else:
            log.warning(f"  No data for resolution {resolution}")
    
    # Phase 3: Aggregate to Res 5
    log.info("\n" + "=" * 70)
    log.info("PHASE 3: Aggregating to Res 5")
    log.info("=" * 70)
    
    phase_start = time.time()
    res8_path = FINAL_OUTPUT / "earth_matrix_london_res8.parquet"
    if res8_path.exists():
        import pandas as pd
        res8 = pd.read_parquet(res8_path)
        res5 = aggregate_to_res5(res8)
        
        if res5 is not None and not res5.empty:
            output_path = FINAL_OUTPUT / "earth_matrix_london_res5.parquet"
            res5.to_parquet(output_path, compression='zstd')
            
            perf_log["phases"]["res5_aggregation"] = {
                "duration_seconds": time.time() - phase_start,
                "rows": len(res5),
                "columns": len(res5.columns),
                "file_size_mb": output_path.stat().st_size / (1024*1024)
            }
            
            log.info(f"  Rows: {len(res5):,}")
            log.info(f"  Columns: {len(res5.columns):,}")
            log.info(f"  File size: {output_path.stat().st_size / (1024*1024):.1f} MB")
    
    log_phase("res5_aggregation", phase_start)
    
    # Save performance log
    perf_log["end_time"] = datetime.now().isoformat()
    perf_log["total_duration_seconds"] = sum(
        p.get("duration_seconds", 0) for p in perf_log["phases"].values()
    )
    
    with open(FINAL_OUTPUT / "performance_log.json", "w") as f:
        json.dump(perf_log, f, indent=2)
    
    log.info("\n" + "=" * 70)
    log.info("BUILD COMPLETE!")
    log.info("=" * 70)
    log.info(f"Total duration: {perf_log['total_duration_seconds']/60:.1f} minutes")
    log.info(f"Output directory: {FINAL_OUTPUT}")
    
    # List output files
    for f in sorted(FINAL_OUTPUT.glob("*.parquet")):
        log.info(f"  {f.name}: {f.stat().st_size / (1024*1024):.1f} MB")

except Exception as e:
    log.error(f"BUILD FAILED: {e}")
    import traceback
    traceback.print_exc()
    perf_log["error"] = str(e)
    with open("/home/ec2-user/output/performance_log_error.json", "w") as f:
        json.dump(perf_log, f, indent=2)
    raise

PYTHON

echo "=========================================="
echo "BUILD FINISHED - $(date)"
echo "=========================================="

# List output files
ls -lah /home/ec2-user/Leo/output/earth_matrix/

echo "Performance log:"
cat /home/ec2-user/Leo/output/earth_matrix/performance_log.json

USERDATA
)

echo "Launching EC2 instance..."
echo "Instance Type: $INSTANCE_TYPE"
echo "Region: $REGION"
echo "Estimated cost: ~$18/hour"

# Launch instance
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id $AMI_ID \
  --instance-type $INSTANCE_TYPE \
  --key-name $KEY_NAME \
  --security-group-ids $SECURITY_GROUP \
  --user-data "$USER_DATA" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=london-matrix-build},{Key=Project,Value=Leo}]" \
  --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":500,\"VolumeType\":\"gp3\",\"Iops\":16000,\"Throughput\":1000}}]" \
  --query 'Instances[0].InstanceId' \
  --output text)

echo ""
echo "Instance launched: $INSTANCE_ID"
echo ""

# Wait for instance to be running
echo "Waiting for instance to start..."
aws ec2 wait instance-running --instance-ids $INSTANCE_ID

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

echo ""
echo "=========================================="
echo "INSTANCE READY"
echo "=========================================="
echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo ""
echo "SSH Command:"
echo "  ssh -i ~/.ssh/matrix-builder.pem ec2-user@$PUBLIC_IP"
echo ""
echo "Monitor build:"
echo "  ssh -i ~/.ssh/matrix-builder.pem ec2-user@$PUBLIC_IP 'tail -f /var/log/matrix-build.log'"
echo ""
echo "Download results when done:"
echo "  scp -i ~/.ssh/matrix-builder.pem -r ec2-user@$PUBLIC_IP:/home/ec2-user/Leo/output/earth_matrix/*.parquet ."
echo ""
echo "Terminate when done:"
echo "  aws ec2 terminate-instances --instance-ids $INSTANCE_ID"
echo ""

```

## backend/scripts/precompute_global.sh

Original SHA-256: `82cbb849036ec07dfc486e9d10b1b4e6a3535c1f2b98d23307974e92c8045fdb`.

```bash
#!/bin/bash
# =============================================================================
# Global Population H3 Pre-computation
# =============================================================================
#
# This script processes ALL GHS-POP tiles globally and uploads to S3.
#
# Options:
#   1. LOCAL:     Run on your machine (slow, ~100 hours)
#   2. EC2:       Spin up instances to process in parallel (~5-10 hours)
#   3. EXISTING:  Use Kontur global data (already H3, but res 8 not res 10)
#
# Usage:
#   ./precompute_global.sh local     # Run locally (background)
#   ./precompute_global.sh ec2 10    # Use 10 EC2 instances
#   ./precompute_global.sh status    # Check progress
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
S3_BUCKET="puedo-casa-population"
S3_REGION="us-west-2"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=============================================="
echo "🌍 Global Population H3 Pre-computation"
echo "=============================================="

case "${1:-help}" in
    local)
        echo -e "${YELLOW}Running locally (this will take ~100 hours)${NC}"
        echo "Processing in background..."
        
        cd "$PROJECT_ROOT"
        nohup python -m Leo.backend.scripts.precompute_population_h3 --all \
            > logs/precompute_global.log 2>&1 &
        
        echo "Started! PID: $!"
        echo "Monitor: tail -f logs/precompute_global.log"
        ;;
        
    ec2)
        NUM_INSTANCES=${2:-10}
        echo -e "${GREEN}Launching $NUM_INSTANCES EC2 instances...${NC}"
        
        # Calculate tile ranges for each instance
        TOTAL_TILES=648
        TILES_PER_INSTANCE=$((TOTAL_TILES / NUM_INSTANCES))
        
        echo "Each instance will process ~$TILES_PER_INSTANCE tiles"
        echo ""
        echo "This will:"
        echo "  1. Launch $NUM_INSTANCES t3.medium instances"
        echo "  2. Each processes its tile range"
        echo "  3. Upload results to s3://$S3_BUCKET/"
        echo "  4. Auto-terminate when done"
        echo ""
        echo "Estimated:"
        echo "  - Time: ~$((100 / NUM_INSTANCES)) hours"
        echo "  - Cost: ~\$$(echo "scale=2; $NUM_INSTANCES * 0.04 * (100 / $NUM_INSTANCES)" | bc)"
        echo ""
        read -p "Proceed? (y/n) " -n 1 -r
        echo
        
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            python "$SCRIPT_DIR/launch_ec2_workers.py" --instances $NUM_INSTANCES
        fi
        ;;
        
    status)
        echo "📊 Checking progress..."
        
        # Check S3
        echo ""
        echo "S3 Status (s3://$S3_BUCKET/):"
        aws s3 ls "s3://$S3_BUCKET/h3_res10/" --recursive --summarize 2>/dev/null | tail -3 || echo "  (bucket not found or empty)"
        
        # Check local
        LOCAL_DIR="$PROJECT_ROOT/Leo/backend/data/population_h3"
        if [ -d "$LOCAL_DIR" ]; then
            echo ""
            echo "Local cache ($LOCAL_DIR):"
            find "$LOCAL_DIR" -name "*.parquet" | wc -l | xargs -I {} echo "  {} parquet files"
            du -sh "$LOCAL_DIR" 2>/dev/null | awk '{print "  Size: " $1}'
        fi
        
        # Check running processes
        echo ""
        echo "Running processes:"
        pgrep -f "precompute_population" && ps aux | grep precompute_population | grep -v grep || echo "  (none)"
        ;;
        
    upload)
        echo "📤 Uploading local cache to S3..."
        LOCAL_DIR="$PROJECT_ROOT/Leo/backend/data/population_h3"
        
        if [ ! -d "$LOCAL_DIR" ]; then
            echo -e "${RED}No local data found at $LOCAL_DIR${NC}"
            exit 1
        fi
        
        aws s3 sync "$LOCAL_DIR" "s3://$S3_BUCKET/h3_res10/" \
            --storage-class INTELLIGENT_TIERING
        
        echo -e "${GREEN}✅ Upload complete!${NC}"
        ;;
        
    test)
        echo "🧪 Testing query speed..."
        cd "$PROJECT_ROOT"
        python -c "
from Leo.backend.tools.tools_population_fast import get_population_fast, check_population_data_status
import time

status = check_population_data_status()
print(f'S3 available: {status[\"s3_available\"]}')
print(f'Local available: {status[\"local_available\"]}')

if status['s3_available'] or status['local_available']:
    # Test Tokyo
    start = time.time()
    result = get_population_fast([139.7, 35.65, 139.75, 35.7])
    elapsed = time.time() - start
    if result:
        print(f'✅ Query returned {len(result)} hexagons in {elapsed:.2f}s')
    else:
        print('❌ No data returned')
else:
    print('⚠️  No pre-computed data available yet')
"
        ;;
        
    *)
        echo "Usage: $0 {local|ec2|status|upload|test}"
        echo ""
        echo "Commands:"
        echo "  local       Process all tiles locally (slow, ~100 hours)"
        echo "  ec2 N       Launch N EC2 instances for parallel processing"
        echo "  status      Check processing progress"
        echo "  upload      Upload local cache to S3"
        echo "  test        Test query speed"
        echo ""
        echo "Recommended workflow:"
        echo "  1. ./precompute_global.sh ec2 10    # Process globally"
        echo "  2. ./precompute_global.sh status    # Monitor progress"
        echo "  3. ./precompute_global.sh test      # Verify it works"
        ;;
esac

```

## backend/scripts/upload_worldpop_to_s3.py

Original SHA-256: `fc464ffa2167328e09de7a4d86b6391ef514d8efa5d77716cfc1b4251014e9a7`.

```python
#!/usr/bin/env python3
"""
Upload WorldPop R2025A data to S3 as Cloud-Optimized GeoTIFFs (COGs)

This script:
1. Downloads WorldPop R2025A data from HDX/WorldPop
2. Converts to Cloud-Optimized GeoTIFF format
3. Uploads to S3 for instant range-read access

Usage:
    # Upload specific countries
    python upload_worldpop_to_s3.py ESP FRA DEU
    
    # Upload all 241 countries (takes ~18 hours)
    python upload_worldpop_to_s3.py --all
    
    # Upload priority countries (top 50 by population)
    python upload_worldpop_to_s3.py --priority
    
    # Include age/sex data (WARNING: much larger files!)
    python upload_worldpop_to_s3.py ESP --include-agesex
"""

import os
import sys
import subprocess
import tempfile
import shutil
import logging
import argparse
import requests
from pathlib import Path
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
S3_BUCKET = "puedo-casa-html-archive"
S3_PREFIX = "worldpop"
WORLDPOP_BASE_URL = "https://data.worldpop.org/GIS"
DEFAULT_YEAR = 2026

# URL patterns
POPULATION_URL = "{base}/Population/Global_2015_2030/R2025A/{year}/{iso3_upper}/v1/100m/constrained/{iso3_lower}_pop_{year}_CN_100m_R2025A_v1.tif"
AGESEX_URL = "{base}/AgeSex_structures/Global_2015_2030/R2025A/{year}/{iso3_upper}/v1/100m/{iso3_lower}_agesex_structures_{year}_CN_100m_R2025A_v1.zip"

# Priority countries (top 50 by population + key markets)
PRIORITY_COUNTRIES = [
    'CHN', 'IND', 'USA', 'IDN', 'PAK', 'BRA', 'NGA', 'BGD', 'RUS', 'MEX',
    'JPN', 'ETH', 'PHL', 'EGY', 'VNM', 'COD', 'TUR', 'IRN', 'DEU', 'THA',
    'GBR', 'FRA', 'ITA', 'TZA', 'ZAF', 'KEN', 'MMR', 'KOR', 'COL', 'ESP',
    'UGA', 'ARG', 'DZA', 'SDN', 'UKR', 'IRQ', 'AFG', 'POL', 'CAN', 'MAR',
    'SAU', 'UZB', 'PER', 'AGO', 'MYS', 'MOZ', 'GHA', 'YEM', 'NPL', 'VEN',
]

# All 241 countries (will be fetched from HDX)
def get_all_countries() -> List[str]:
    """Fetch all available countries from HDX."""
    try:
        url = "https://data.humdata.org/api/3/action/package_search"
        params = {'q': 'worldpop-population-counts-2015-2030', 'rows': 300}
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        
        countries = []
        for result in data.get('result', {}).get('results', []):
            name = result.get('name', '')
            if 'population-counts-2015-2030' in name:
                iso3 = name.split('-')[-1].upper()
                if len(iso3) == 3:
                    countries.append(iso3)
        
        return sorted(set(countries))
    except Exception as e:
        logger.error(f"Failed to fetch country list: {e}")
        return PRIORITY_COUNTRIES


def check_s3_exists(s3_path: str) -> bool:
    """Check if file exists on S3."""
    result = subprocess.run(
        ['aws', 's3', 'ls', s3_path],
        capture_output=True, text=True
    )
    return result.returncode == 0 and len(result.stdout.strip()) > 0


def download_file(url: str, dest: Path, desc: str = "") -> bool:
    """Download file with progress."""
    logger.info(f"📥 Downloading {desc}: {url[:80]}...")
    try:
        response = requests.get(url, stream=True, timeout=600)
        response.raise_for_status()
        
        total = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(dest, 'wb') as f:
            for chunk in response.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and downloaded % (10 * 1024 * 1024) < 65536:
                    pct = (downloaded / total) * 100
                    logger.info(f"   {downloaded / (1024*1024):.0f} MB / {total / (1024*1024):.0f} MB ({pct:.0f}%)")
        
        return True
    except Exception as e:
        logger.error(f"❌ Download failed: {e}")
        return False


def convert_to_cog(input_path: Path, output_path: Path) -> bool:
    """Convert GeoTIFF to Cloud-Optimized GeoTIFF."""
    logger.info(f"🔄 Converting to COG: {input_path.name}")
    try:
        result = subprocess.run(
            ['rio', 'cogeo', 'create', str(input_path), str(output_path), '--overview-level', '5'],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            logger.error(f"COG conversion failed: {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"❌ COG conversion failed: {e}")
        return False


def upload_to_s3(local_path: Path, s3_path: str) -> bool:
    """Upload file to S3."""
    logger.info(f"☁️ Uploading to S3: {s3_path}")
    try:
        result = subprocess.run(
            ['aws', 's3', 'cp', str(local_path), s3_path, '--no-progress'],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            logger.error(f"S3 upload failed: {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"❌ S3 upload failed: {e}")
        return False


def process_country_population(iso3: str, year: int = DEFAULT_YEAR, force: bool = False) -> bool:
    """Download, convert, and upload population data for one country."""
    s3_key = f"s3://{S3_BUCKET}/{S3_PREFIX}/{iso3}/{iso3.lower()}_pop_{year}_COG.tif"
    
    # Check if already uploaded
    if not force and check_s3_exists(s3_key):
        logger.info(f"✅ {iso3} population {year} already on S3, skipping")
        return True
    
    # Build download URL
    url = POPULATION_URL.format(
        base=WORLDPOP_BASE_URL,
        year=year,
        iso3_upper=iso3.upper(),
        iso3_lower=iso3.lower()
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Download
        raw_file = tmpdir / f"{iso3.lower()}_pop_{year}_raw.tif"
        if not download_file(url, raw_file, f"{iso3} population {year}"):
            return False
        
        # Convert to COG
        cog_file = tmpdir / f"{iso3.lower()}_pop_{year}_COG.tif"
        if not convert_to_cog(raw_file, cog_file):
            return False
        
        # Upload to S3
        if not upload_to_s3(cog_file, s3_key):
            return False
    
    logger.info(f"✅ {iso3} population {year} uploaded successfully!")
    return True


def process_country_agesex(iso3: str, year: int = DEFAULT_YEAR, force: bool = False) -> bool:
    """Download, convert, and upload age/sex data for one country."""
    # This downloads a ZIP with multiple TIFs, converts each to COG
    s3_prefix = f"s3://{S3_BUCKET}/{S3_PREFIX}/{iso3}/agesex_{year}/"
    
    # Check if already uploaded (check for at least one file)
    test_key = f"{s3_prefix}{iso3.lower()}_f_0_2020_COG.tif"  # Example file
    if not force and check_s3_exists(test_key):
        logger.info(f"✅ {iso3} age/sex {year} already on S3, skipping")
        return True
    
    url = AGESEX_URL.format(
        base=WORLDPOP_BASE_URL,
        year=year,
        iso3_upper=iso3.upper(),
        iso3_lower=iso3.lower()
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Download ZIP
        zip_file = tmpdir / f"{iso3.lower()}_agesex_{year}.zip"
        if not download_file(url, zip_file, f"{iso3} age/sex {year}"):
            return False
        
        # Extract
        extract_dir = tmpdir / "extracted"
        logger.info(f"📦 Extracting {zip_file.name}...")
        import zipfile
        with zipfile.ZipFile(zip_file, 'r') as zf:
            zf.extractall(extract_dir)
        
        # Convert each TIF to COG and upload
        tif_files = list(extract_dir.rglob("*.tif"))
        logger.info(f"   Found {len(tif_files)} TIF files")
        
        for i, tif_file in enumerate(tif_files):
            cog_file = tmpdir / f"{tif_file.stem}_COG.tif"
            
            if not convert_to_cog(tif_file, cog_file):
                continue
            
            s3_key = f"{s3_prefix}{tif_file.stem}_COG.tif"
            if not upload_to_s3(cog_file, s3_key):
                continue
            
            # Clean up COG to save space
            cog_file.unlink()
            
            if (i + 1) % 10 == 0:
                logger.info(f"   Processed {i + 1}/{len(tif_files)} files")
    
    logger.info(f"✅ {iso3} age/sex {year} uploaded successfully!")
    return True


def main():
    parser = argparse.ArgumentParser(description='Upload WorldPop data to S3 as COGs')
    parser.add_argument('countries', nargs='*', help='ISO3 country codes (e.g., ESP FRA DEU)')
    parser.add_argument('--all', action='store_true', help='Upload all 241 countries')
    parser.add_argument('--priority', action='store_true', help='Upload top 50 priority countries')
    parser.add_argument('--include-agesex', action='store_true', help='Also upload age/sex data (large!)')
    parser.add_argument('--year', type=int, default=DEFAULT_YEAR, help='Year (2015-2030)')
    parser.add_argument('--force', action='store_true', help='Re-upload even if exists')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be uploaded')
    
    args = parser.parse_args()
    
    # Determine which countries to process
    if args.all:
        countries = get_all_countries()
    elif args.priority:
        countries = PRIORITY_COUNTRIES
    elif args.countries:
        countries = [c.upper() for c in args.countries]
    else:
        print("Usage: python upload_worldpop_to_s3.py ESP FRA DEU")
        print("       python upload_worldpop_to_s3.py --priority")
        print("       python upload_worldpop_to_s3.py --all")
        sys.exit(1)
    
    logger.info(f"=" * 60)
    logger.info(f"WorldPop to S3 Uploader")
    logger.info(f"   Countries: {len(countries)}")
    logger.info(f"   Year: {args.year}")
    logger.info(f"   Include age/sex: {args.include_agesex}")
    logger.info(f"=" * 60)
    
    if args.dry_run:
        for iso3 in countries:
            print(f"Would upload: {iso3} population {args.year}")
            if args.include_agesex:
                print(f"Would upload: {iso3} age/sex {args.year}")
        sys.exit(0)
    
    # Process countries
    success = 0
    failed = []
    
    for i, iso3 in enumerate(countries):
        logger.info(f"\n[{i+1}/{len(countries)}] Processing {iso3}...")
        
        if process_country_population(iso3, args.year, args.force):
            success += 1
        else:
            failed.append(iso3)
        
        if args.include_agesex:
            process_country_agesex(iso3, args.year, args.force)
    
    # Summary
    logger.info(f"\n" + "=" * 60)
    logger.info(f"✅ Completed: {success}/{len(countries)} countries")
    if failed:
        logger.info(f"❌ Failed: {failed}")
    logger.info(f"=" * 60)


if __name__ == "__main__":
    main()
```

## backend/scripts/precompute_population_h3.py

Original SHA-256: `3075de57a06abe0ae99268f59d8302249258a2b960747e6744bc2dd7d53c05ec`.

```python
#!/usr/bin/env python3
"""
Pre-compute Global Population H3 Grid from GHS-POP
===================================================

This script converts Copernicus GHS-POP raster data to H3 hexagon parquet files
that can be queried instantly with DuckDB (like Overture Maps).

Output Structure (S3):
    s3://puedo-casa-population/h3_res8/
        ├── 80/  (H3 res-0 prefix for partitioning)
        │   ├── population_80.parquet
        │   └── ...
        ├── 81/
        └── ...

Each parquet file contains:
    - hex: H3 cell index (resolution 8)
    - population: Population count
    - lat: Cell center latitude
    - lng: Cell center longitude

Query Example:
    SELECT * FROM read_parquet('s3://puedo-casa-population/h3_res8/*/*.parquet')
    WHERE hex LIKE '88...'  -- Filter by H3 prefix for bbox

Cost Estimate:
    - Storage: ~2-5 GB for global data = ~$0.12/month
    - Queries: ~$0.005 per query (scan ~100MB)
    - Total: ~$2/month for moderate usage

Usage:
    # Process a single tile (for testing)
    python precompute_population_h3.py --tile R5_C19  # Tokyo area
    
    # Process all tiles (full global coverage)
    python precompute_population_h3.py --all
    
    # Upload to S3
    python precompute_population_h3.py --upload

Requirements:
    pip install rasterio h3 pandas pyarrow boto3 tqdm
"""

import os
import sys
import argparse
import logging
import tempfile
import zipfile
import requests
import numpy as np
import pandas as pd
import h3
from pathlib import Path
from typing import Optional, Tuple, List
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# GHS-POP source (same as tools_demographics.py)
GHS_TILES_BASE = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
    "GHS_POP_GLOBE_R2023A/GHS_POP_E2025_GLOBE_R2023A_4326_3ss/V1-0/tiles"
)

# Output configuration
OUTPUT_DIR = Path("./data/population_h3")
S3_BUCKET = "puedo-casa-population"
S3_PREFIX = "h3_res8"

# H3 resolution options:
#   8 = ~460m edge (neighborhood) - ~2GB global, fast queries
#   9 = ~174m edge (street level) - ~15GB global, recommended
#  10 = ~66m edge (building level) - ~100GB global, detailed
H3_RESOLUTION = 10  # Building level for detailed analysis

# Tile grid (18 rows x 36 cols, each 10° x 10°)
TILE_ROWS = 18
TILE_COLS = 36

# =============================================================================
# REGIONAL PRESETS (process just the areas you need)
# =============================================================================

REGIONS = {
    # Format: 'name': [(row, col), (row, col), ...]
    # Row 1 = 80-90°N, Row 18 = 80-90°S
    # Col 1 = 180-170°W, Col 36 = 170-180°E
    
    'japan': [
        (5, 32), (5, 33),  # Northern Japan (Hokkaido)
        (6, 32), (6, 33),  # Central Japan (Tokyo, Osaka)
        (7, 32), (7, 33),  # Southern Japan (Kyushu)
    ],
    
    'tokyo': [
        (6, 33),  # Tokyo metro area (single tile)
    ],
    
    'europe_west': [
        (5, 18), (5, 19), (5, 20),  # UK, Ireland, France north
        (6, 18), (6, 19), (6, 20),  # Spain, France, Germany
    ],
    
    'usa_east': [
        (5, 8), (5, 9), (5, 10),   # Northeast
        (6, 8), (6, 9), (6, 10),   # Southeast
    ],
    
    'usa_west': [
        (5, 5), (5, 6), (5, 7),    # Pacific Northwest
        (6, 5), (6, 6), (6, 7),    # California, Southwest
    ],
    
    'china_east': [
        (5, 29), (5, 30), (5, 31),  # Northern China
        (6, 29), (6, 30), (6, 31),  # Eastern China (Shanghai, etc)
    ],
    
    'india': [
        (6, 26), (6, 27),  # Northern India
        (7, 26), (7, 27),  # Southern India
    ],
    
    'brazil': [
        (8, 12), (8, 13),   # Northern Brazil
        (9, 12), (9, 13),   # Central Brazil
        (10, 12), (10, 13), # Southern Brazil
    ],
    
    'africa_west': [
        (7, 18), (7, 19),  # West Africa (Ghana, Nigeria)
        (8, 18), (8, 19),  # Central West Africa
    ],
    
    # Time estimates at H3 res 10:
    # - tokyo: ~10 minutes (1 tile)
    # - japan: ~45 minutes (6 tiles)
    # - europe_west: ~2 hours (6 tiles)
    # - usa_east: ~2 hours (6 tiles)
}


# =============================================================================
# TILE PROCESSING
# =============================================================================

def download_tile(row: int, col: int, cache_dir: Path) -> Optional[Path]:
    """Download a GHS-POP tile if not cached."""
    tile_name = f"GHS_POP_E2025_GLOBE_R2023A_4326_3ss_V1_0_R{row}_C{col}"
    tif_path = cache_dir / f"{tile_name}.tif"
    
    if tif_path.exists():
        logger.debug(f"Using cached: R{row}_C{col}")
        return tif_path
    
    zip_url = f"{GHS_TILES_BASE}/{tile_name}.zip"
    zip_path = cache_dir / f"{tile_name}.zip"
    
    logger.info(f"Downloading R{row}_C{col}...")
    
    try:
        response = requests.get(zip_url, stream=True, timeout=120)
        if response.status_code == 404:
            logger.debug(f"Tile R{row}_C{col} not found (ocean/unpopulated)")
            return None
        response.raise_for_status()
        
        # Download with progress
        total = int(response.headers.get('content-length', 0))
        with open(zip_path, 'wb') as f:
            for chunk in tqdm(response.iter_content(8192), 
                            total=total//8192, 
                            desc=f"R{row}_C{col}",
                            leave=False):
                f.write(chunk)
        
        # Extract
        with zipfile.ZipFile(zip_path, 'r') as zf:
            tif_files = [f for f in zf.namelist() if f.endswith('.tif')]
            if tif_files:
                zf.extract(tif_files[0], cache_dir)
                extracted = cache_dir / tif_files[0]
                if extracted != tif_path:
                    extracted.rename(tif_path)
        
        zip_path.unlink()
        return tif_path
        
    except Exception as e:
        logger.warning(f"Failed R{row}_C{col}: {e}")
        if zip_path.exists():
            zip_path.unlink()
        return None


def process_tile_to_h3(tif_path: Path, resolution: int = H3_RESOLUTION) -> pd.DataFrame:
    """
    Convert a GHS-POP GeoTIFF tile to H3 hexagon DataFrame.
    
    Args:
        tif_path: Path to the GeoTIFF file
        resolution: H3 resolution (default 8)
        
    Returns:
        DataFrame with columns: hex, population, lat, lng
    """
    import rasterio
    
    logger.info(f"Processing {tif_path.name}...")
    
    h3_data = {}
    
    with rasterio.open(tif_path) as src:
        data = src.read(1)
        transform = src.transform
        
        rows, cols = data.shape
        logger.info(f"  Tile size: {rows}x{cols} pixels")
        
        # Process in chunks for memory efficiency
        chunk_size = 1000
        total_chunks = (rows // chunk_size + 1) * (cols // chunk_size + 1)
        
        with tqdm(total=total_chunks, desc="  Processing", leave=False) as pbar:
            for r_start in range(0, rows, chunk_size):
                for c_start in range(0, cols, chunk_size):
                    r_end = min(r_start + chunk_size, rows)
                    c_end = min(c_start + chunk_size, cols)
                    
                    for r in range(r_start, r_end):
                        for c in range(c_start, c_end):
                            pop_value = data[r, c]
                            
                            # Skip NoData/zero
                            if pop_value <= 0 or np.isnan(pop_value):
                                continue
                            
                            # Get coordinates
                            lon, lat = rasterio.transform.xy(transform, r, c)
                            
                            # Convert to H3
                            hex_id = h3.latlng_to_cell(lat, lon, resolution)
                            
                            # Aggregate population per hex
                            h3_data[hex_id] = h3_data.get(hex_id, 0) + pop_value
                    
                    pbar.update(1)
    
    # Convert to DataFrame
    if not h3_data:
        return pd.DataFrame(columns=['hex', 'population', 'lat', 'lng'])
    
    records = []
    for hex_id, pop in h3_data.items():
        lat, lng = h3.cell_to_latlng(hex_id)
        records.append({
            'hex': hex_id,
            'population': int(round(pop)),
            'lat': round(lat, 6),
            'lng': round(lng, 6)
        })
    
    df = pd.DataFrame(records)
    logger.info(f"  Generated {len(df)} H3 hexagons, total pop: {df['population'].sum():,}")
    
    return df


def save_parquet(df: pd.DataFrame, tile_row: int, tile_col: int, output_dir: Path):
    """Save DataFrame as parquet, partitioned by H3 prefix."""
    if df.empty:
        return
    
    # Get H3 res-0 prefix for partitioning (first 2 chars after '8')
    # This creates ~122 partitions globally
    df['h3_prefix'] = df['hex'].str[:3]
    
    for prefix, group in df.groupby('h3_prefix'):
        partition_dir = output_dir / prefix
        partition_dir.mkdir(parents=True, exist_ok=True)
        
        out_path = partition_dir / f"R{tile_row}_C{tile_col}.parquet"
        group.drop(columns=['h3_prefix']).to_parquet(out_path, index=False)
    
    logger.info(f"  Saved to {output_dir}")


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_single_tile(row: int, col: int, cache_dir: Path, output_dir: Path):
    """Process a single GHS-POP tile."""
    tif_path = download_tile(row, col, cache_dir)
    
    if tif_path is None:
        logger.info(f"Tile R{row}_C{col} not available (ocean/unpopulated)")
        return
    
    df = process_tile_to_h3(tif_path)
    save_parquet(df, row, col, output_dir)


def process_all_tiles(cache_dir: Path, output_dir: Path, skip_existing: bool = True):
    """Process all GHS-POP tiles globally."""
    logger.info(f"Processing all {TILE_ROWS * TILE_COLS} tiles...")
    
    for row in range(1, TILE_ROWS + 1):
        for col in range(1, TILE_COLS + 1):
            # Check if already processed
            if skip_existing:
                # Check if any parquet exists for this tile
                existing = list(output_dir.glob(f"*/R{row}_C{col}.parquet"))
                if existing:
                    logger.debug(f"Skipping R{row}_C{col} (already processed)")
                    continue
            
            try:
                process_single_tile(row, col, cache_dir, output_dir)
            except Exception as e:
                logger.error(f"Error processing R{row}_C{col}: {e}")
                continue


def upload_to_s3(local_dir: Path, bucket: str, prefix: str):
    """Upload processed parquet files to S3."""
    import boto3
    
    logger.info(f"Uploading to s3://{bucket}/{prefix}/...")
    
    s3 = boto3.client('s3')
    
    parquet_files = list(local_dir.glob("**/*.parquet"))
    logger.info(f"Found {len(parquet_files)} parquet files")
    
    for pq_file in tqdm(parquet_files, desc="Uploading"):
        # Preserve partition structure
        relative_path = pq_file.relative_to(local_dir)
        s3_key = f"{prefix}/{relative_path}"
        
        s3.upload_file(str(pq_file), bucket, s3_key)
    
    logger.info(f"✅ Uploaded to s3://{bucket}/{prefix}/")


# =============================================================================
# QUERY HELPER (for tools_demographics.py)
# =============================================================================

def query_population_h3_s3(
    bbox: list,
    bucket: str = S3_BUCKET,
    prefix: str = S3_PREFIX,
    resolution: int = H3_RESOLUTION
) -> list[dict]:
    """
    Query pre-computed population H3 data from S3.
    
    This is the FAST version - replaces fetch_ghs_population().
    Should return in <2 seconds for any bbox.
    
    Args:
        bbox: [west, south, east, north]
        bucket: S3 bucket name
        prefix: S3 prefix
        resolution: H3 resolution (must match pre-computed data)
        
    Returns:
        List of dicts [{'hex': '...', 'count': 1234}, ...]
    """
    import duckdb
    
    west, south, east, north = bbox
    
    # Initialize DuckDB with S3 access
    conn = duckdb.connect()
    conn.execute("INSTALL httpfs; LOAD httpfs;")
    conn.execute("SET s3_region='us-west-2';")
    
    # Query with bbox filter
    # DuckDB will use partition pruning on h3_prefix
    query = f"""
    SELECT hex, population as count
    FROM read_parquet('s3://{bucket}/{prefix}/*/*.parquet')
    WHERE lat >= {south} AND lat <= {north}
      AND lng >= {west} AND lng <= {east}
    """
    
    result = conn.execute(query).fetchdf()
    conn.close()
    
    return result.to_dict('records')


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Pre-compute GHS-POP to H3 parquet")
    parser.add_argument('--tile', type=str, help="Single tile (e.g., R5_C19 for Tokyo)")
    parser.add_argument('--all', action='store_true', help="Process all tiles")
    parser.add_argument('--upload', action='store_true', help="Upload to S3")
    parser.add_argument('--output', type=str, default=str(OUTPUT_DIR), help="Output directory")
    parser.add_argument('--cache', type=str, default='/tmp/ghs_cache', help="Tile cache directory")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    cache_dir = Path(args.cache)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    if args.tile:
        # Parse tile ID (e.g., "R5_C19")
        parts = args.tile.upper().replace('R', '').replace('C', '_').split('_')
        row, col = int(parts[0]), int(parts[1])
        logger.info(f"Processing single tile: R{row}_C{col}")
        process_single_tile(row, col, cache_dir, output_dir)
        
    elif args.all:
        logger.info("Processing all global tiles...")
        process_all_tiles(cache_dir, output_dir)
        
    elif args.upload:
        upload_to_s3(output_dir, S3_BUCKET, S3_PREFIX)
        
    else:
        parser.print_help()
        print("\n📋 Quick Start:")
        print("  1. Test with Tokyo: python precompute_population_h3.py --tile R5_C19")
        print("  2. Process all:     python precompute_population_h3.py --all")
        print("  3. Upload to S3:    python precompute_population_h3.py --upload")


if __name__ == "__main__":
    main()

```
