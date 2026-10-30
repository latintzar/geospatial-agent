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

