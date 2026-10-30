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
