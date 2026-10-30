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

