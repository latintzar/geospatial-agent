#!/bin/bash
# =============================================================================
# Monitor Earth Matrix Build Progress
# =============================================================================
#
# Usage:
#   ./monitor.sh <instance-ip>           # Watch main log
#   ./monitor.sh <instance-ip> --status  # Show phase progress
#   ./monitor.sh <instance-ip> --files   # Show output files
#
# =============================================================================

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <instance-ip> [--status|--files|--log]"
    exit 1
fi

INSTANCE_IP="$1"
MODE="${2:---log}"
KEY_PATH="${KEY_PATH:-~/.ssh/earth-matrix-key.pem}"

case "$MODE" in
    --log)
        echo "Streaming log from $INSTANCE_IP..."
        echo "Press Ctrl+C to stop"
        echo ""
        ssh -i "$KEY_PATH" ec2-user@"$INSTANCE_IP" "tail -f /var/log/earth_matrix.log"
        ;;
        
    --status)
        echo "============================================================"
        echo "Earth Matrix Build Status"
        echo "============================================================"
        echo ""
        
        ssh -i "$KEY_PATH" ec2-user@"$INSTANCE_IP" << 'REMOTE'
echo "Phase 1 (Hex Fill):"
HEX_COUNT=$(ls /tmp/earth_matrix/hex_fill/*.parquet 2>/dev/null | wc -l)
echo "  Completed chunks: $HEX_COUNT / 67"
echo ""

echo "Phase 2 (Propagation):"
MATRIX_COUNT=$(ls /tmp/earth_matrix/matrix/*.parquet 2>/dev/null | wc -l)
EXPECTED=$((67 * 3))  # 67 chunks × 3 resolutions
echo "  Completed: $MATRIX_COUNT / $EXPECTED"
echo ""

echo "Phase 3 (Final Output):"
if [ -d /data/earth_matrix ]; then
    ls -lh /data/earth_matrix/*.parquet 2>/dev/null || echo "  No final files yet"
else
    echo "  Not started"
fi
echo ""

echo "System Resources:"
echo "  Memory: $(free -h | awk '/^Mem:/ {print $3 "/" $2}')"
echo "  Disk:   $(df -h /tmp | awk 'NR==2 {print $3 "/" $2}')"
echo "  Load:   $(uptime | awk -F'load average:' '{print $2}')"
REMOTE
        ;;
        
    --files)
        echo "============================================================"
        echo "Earth Matrix Output Files"
        echo "============================================================"
        echo ""
        
        ssh -i "$KEY_PATH" ec2-user@"$INSTANCE_IP" << 'REMOTE'
echo "Intermediate files:"
echo ""
echo "/tmp/earth_matrix/hex_fill/:"
ls -lhS /tmp/earth_matrix/hex_fill/*.parquet 2>/dev/null | head -10
echo "..."
echo "Total: $(ls /tmp/earth_matrix/hex_fill/*.parquet 2>/dev/null | wc -l) files"
echo ""

echo "/tmp/earth_matrix/matrix/:"
ls -lhS /tmp/earth_matrix/matrix/*.parquet 2>/dev/null | head -10
echo "..."
echo "Total: $(ls /tmp/earth_matrix/matrix/*.parquet 2>/dev/null | wc -l) files"
echo ""

echo "Final output:"
if [ -d /data/earth_matrix ]; then
    ls -lh /data/earth_matrix/
else
    echo "  No final output yet"
fi
REMOTE
        ;;
        
    --errors)
        echo "Checking for errors..."
        ssh -i "$KEY_PATH" ec2-user@"$INSTANCE_IP" \
            "grep -i 'error\|failed\|exception' /var/log/earth_matrix.log | tail -50"
        ;;
        
    *)
        echo "Unknown mode: $MODE"
        echo "Options: --log, --status, --files, --errors"
        exit 1
        ;;
esac

