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

