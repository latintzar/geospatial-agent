# Earth Matrix Benchmarks

This directory contains benchmark results from test builds used to extrapolate global costs.

## Running a Test Build

The same `build_global_matrix.py` script handles both test and global builds. The only differences:
- **Test mode**: Smaller bounding box, fewer workers, benchmarking enabled
- **Global mode**: Full planet, max parallelism, no benchmarking overhead

### Quick Start (Hoxton - ~4 km²)

```bash
cd /Users/peterneyra/puedo_casa/Leo

# Test mode with CLI flags
python backend/etl/global/build_global_matrix.py --test-mode --test-region hoxton

# Or via environment variables
TEST_MODE=true TEST_REGION=hoxton python backend/etl/global/build_global_matrix.py
```

### Test Region Options

```bash
# Hoxton (smallest, fastest - ~4 km²)
python backend/etl/global/build_global_matrix.py --test-region hoxton

# Greater London (~1,572 km²)
python backend/etl/global/build_global_matrix.py --test-region greater_london

# Full UK (~244,000 km²)
python backend/etl/global/build_global_matrix.py --test-region uk
```

### Full Build (Global)

```bash
# Production global build (on m8i.96xlarge)
python backend/etl/global/build_global_matrix.py
```

## Output Structure

After running a test, you'll find:

```
benchmarks/{region}_test/
├── system_metrics.csv       # 1-second CPU/RAM/Disk/Network samples
├── task_metrics.json        # Per-phase timing breakdown
├── business_metrics.json    # POI counts, hex counts, rates
├── s3_egress.json           # S3 bytes read, estimated cost
├── cost_extrapolation.json  # Projected global costs
└── summary.json             # High-level summary

output/earth_matrix/
├── earth_matrix_res5.parquet
├── earth_matrix_res8.parquet
├── earth_matrix_res10.parquet
└── earth_matrix_res11.parquet
```

## Interpreting Results

### cost_extrapolation.json

```json
{
  "test_region": {
    "area_km2": 4.25,
    "duration_s": 120,
    "poi_count": 5000,
    "s3_mb": 50
  },
  "cost_estimates": {
    "compute_usd": 162.56,
    "s3_egress_usd": 3.50,
    "total_usd": 166.06
  }
}
```

### Key Metrics to Check

| Metric | What It Means |
|--------|---------------|
| `propagation_rate` | POI k-ring operations per second |
| `s3_egress.total_mb` | Data pulled from Overture S3 ($5/TB) |
| `ram_peak_gb` | Memory high-water mark |
| `cpu_avg_percent` | CPU utilization during build |

### Global Cost Formula

```
Global Compute = (Duration × Area Scale × POI Density Adj) / Parallelism Gain × EC2 Rate
Global S3 Cost = S3 Bytes × Area Scale × $5/TB
```

Where:
- **Area Scale** = Global Inhabited (60M km²) / Test Area
- **POI Density Adj** = 0.3 (global avg density vs urban)
- **Parallelism Gain** = 384 vCPUs / 8 local cores = 48×
- **EC2 Rate** = $20.32/hr (m8i.96xlarge on-demand)

## Test Regions

| Region | Area | Expected Duration | Use Case |
|--------|------|-------------------|----------|
| `hoxton` | ~4 km² | 1-3 min | Quick iteration |
| `greater_london` | ~1,572 km² | 10-30 min | Realistic stress test |
| `uk` | ~244,000 km² | Hours | Full country test |

## Same Code Path Guarantee

The test build runs through the **exact same code** as the global build:
1. Same DuckDB queries to Overture S3
2. Same k-ring propagation algorithm
3. Same 1,081 POI categories
4. Same resolution outputs (5, 8, 10, 11)
5. Same merge logic

The only differences:
- Bounding box is smaller (test region vs planet)
- Parallelism is lower (8 workers vs 384 workers)
- Benchmarking is enabled (tracks metrics)

This ensures test results are reliable predictors of global performance.

## Dependencies

```bash
pip install duckdb h3 pandas psutil
```
