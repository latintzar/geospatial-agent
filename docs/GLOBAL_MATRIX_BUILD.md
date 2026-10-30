# Global Earth Matrix Build Pipeline (ULTRA-MAXED)

> **Build the entire planet with ALL 1,081 Level-3 POI categories in ~8 hours for ~$165 on-demand**
>
> *"A dataset worth $1M+ for $165. Every restaurant type. Every bar type. Every specialty."*

---

## Quick Start

```bash
# Launch the build (one command)
./backend/etl/global/scripts/launch_global_build.sh

# Monitor progress
ssh ec2-user@<instance-ip> "tail -f /var/log/earth_matrix.log"

# Download results when complete
aws s3 sync s3://earth-matrix-output/ ./output/
```

---

## Instance Selection

### Why `m8i.96xlarge`?

| Instance | vCPU | RAM | Network | $/hr | Performance |
|----------|------|-----|---------|------|-------------|
| r7i.48xlarge | 192 | 1.5 TB | 50 Gbps | $12.70 | Baseline |
| **m8i.96xlarge** | **384** | 1.5 TB | **100 Gbps** | $20.32 | **~2× faster** |
| x8g.48xlarge | 192 | 3 TB | 50 Gbps | $18.76 | ❌ ARM (h3-py issues) |

**Key insight:** With 596 POI categories to propagate:
- **192 vCPUs** = ~3 batches per chunk (596 ÷ 192 = 3.1)
- **384 vCPUs** = ~2 batches per chunk (596 ÷ 384 = 1.6)

**2× CPUs = ~2× faster = CHEAPER total cost**

| Instance | Est. Time | Hourly | **Total Cost** |
|----------|-----------|--------|----------------|
| r7i.48xlarge | 16 hr | $12.70 | $203 |
| **m8i.96xlarge** | **8 hr** | $20.32 | **$165** ✅ |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     m8i.96xlarge (384 vCPU, 1.5TB RAM, 100Gbps)             │
│                              Cost: ~$165 on-demand                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PHASE 1: DuckDB Hex Fill                                    ~25 min │   │
│  │ ─────────────────────────────────────────────────────────────────── │   │
│  │ • 50 parallel DuckDB instances (one per geographic chunk)          │   │
│  │ • Reads directly from Overture S3 (no download)                    │   │
│  │ • 100 Gbps network = 2× faster S3 reads                            │   │
│  │                                                                     │   │
│  │ SQL Operations:                                                     │   │
│  │ • h3_polygon_to_cells(geometry, 12) - polygon hex fill             │   │
│  │ • ST_Area_Spheroid(geometry) - area calculation                    │   │
│  │ • h3_latlng_to_cell() - POI/building centroid to hex               │   │
│  │                                                                     │   │
│  │ Output: 50 chunk parquets with raw hex fills + POI locations       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PHASE 2: Python K-Ring Propagation (BATCHED)                ~45 min │   │
│  │ ─────────────────────────────────────────────────────────────────── │   │
│  │ • 384 parallel Python processes                                    │   │
│  │ • 1,081 POI categories per chunk                                   │   │
│  │ • BATCHED: 100 categories/batch = 11 batches per chunk             │   │
│  │                                                                     │   │
│  │ Per Batch (Memory-Safe):                                            │   │
│  │ • Process 100 categories in parallel (380 workers)                 │   │
│  │ • Write batch to temp parquet (chunk_X_batch_N.parquet)            │   │
│  │ • Clear dict from RAM before next batch                            │   │
│  │                                                                     │   │
│  │ Final: DuckDB joins 12 batch parquets into chunk_X_resY.parquet    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PHASE 3: Python Edge Propagation (Polygons)                 ~12 min │   │
│  │ ─────────────────────────────────────────────────────────────────── │   │
│  │ • Parks, beaches, forests, water bodies                            │   │
│  │ • Find edge hexes of each polygon                                  │   │
│  │ • Propagate outward for travel times                               │   │
│  │ • Size-tiered columns (park_20k_walk_min, etc.)                    │   │
│  │                                                                     │   │
│  │ Output: polygon_travel_{chunk}.parquet (50 files)                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PHASE 4: Aggregate & Merge                                   ~8 min │   │
│  │ ─────────────────────────────────────────────────────────────────── │   │
│  │ • Join all propagation results per chunk                           │   │
│  │ • Aggregate Res 10 → Res 8 → Res 5 (counts/areas only)             │   │
│  │ • UNION ALL chunks per resolution                                  │   │
│  │ • Write final ZSTD-compressed parquets                             │   │
│  │                                                                     │   │
│  │ Output Files:                                                       │   │
│  │ • earth_matrix_maxed_res5.parquet   (~2 GB,   ~500K hexes)         │   │
│  │ • earth_matrix_maxed_res8.parquet   (~25 GB,  ~180M hexes)         │   │
│  │ • earth_matrix_maxed_res10.parquet  (~250 GB, ~9B hexes)           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PHASE 5: Upload & Cleanup                                    ~5 min │   │
│  │ ─────────────────────────────────────────────────────────────────── │   │
│  │ • Upload to S3 (parallel, 100 Gbps)                                │   │
│  │ • Self-terminate instance                                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

TOTAL RUNTIME: ~8 hours
TOTAL COST: ~$165 on-demand
```

---

## ULTRA-MAXED Schema (5,745 columns)

### POI Categories: ALL 1,081 Level-3 (Individual Types!)

```
Level-3 Granularity - Every type gets its own columns:

RESTAURANTS (77 types):
├── italian_restaurant_count, italian_restaurant_walk_min, ...
├── japanese_restaurant_count, japanese_restaurant_walk_min, ...
├── mexican_restaurant_count, mexican_restaurant_walk_min, ...
├── thai_restaurant_count, thai_restaurant_walk_min, ...
├── sushi_restaurant, ramen_restaurant, pho_restaurant, ...
└── ... 77 restaurant types × 5 columns = 385 columns

BARS (43 types):
├── wine_bar_count, wine_bar_walk_min, ...
├── cocktail_bar_count, cocktail_bar_walk_min, ...
├── sports_bar, irish_pub, dive_bar, rooftop_bar, ...
└── ... 43 bar types × 5 columns = 215 columns

CAFES (30 types):
├── specialty_coffee, matcha_cafe, bubble_tea, ...
├── bakery, patisserie, donut_shop, ...
└── ... 30 cafe types × 5 columns = 150 columns

ALL CATEGORIES:
├── Restaurants:       77 types
├── Bars:              43 types
├── Cafes:             30 types
├── Accommodation:     34 types (boutique_hotel, hostel, airbnb, ...)
├── Sports Venues:     74 types (crossfit, yoga_studio, boxing_gym, ...)
├── Entertainment:     69 types (comedy_club, escape_room, vr_arcade, ...)
├── Attractions:       57 types (art_museum, science_museum, ...)
├── Automotive:        30 types (ev_charging, tesla_supercharger, ...)
├── Beauty/Spa:        55 types (thai_massage, korean_spa, microblading, ...)
├── Education:         53 types (montessori_school, coding_bootcamp, ...)
├── Financial:         31 types
├── Health/Medical:    92 types (cardiologist, chiropractor, ...)
├── Retail/Shopping:  170 types (vintage_store, sneaker_store, ...)
├── Professional:      44 types
├── Home Service:      56 types
├── Public Service:    41 types
├── Religious:         33 types
├── Travel/Transit:    40 types
├── Real Estate:       20 types
└── Food Specialty:    51 types (poke, acai, ramen, ...)

TOTAL: 1,081 Level-3 POI types × 5 columns = 5,405 POI columns
```

### Other Features

```
Land Use (26 classes × 3 = 78 columns):
├── {class}_count, {class}_area_m2, {class}_avg_area_m2

Water (12 types × 5 = 60 columns):
├── {type}_count, area_m2, walk_min, cycle_min, drive_min

Infrastructure (15 classes × 4 = 60 columns):
├── {class}_count, walk_min, cycle_min, drive_min

Roads (15 classes = 15 columns):
├── {class}_density (m per hex)

Transit (7 types × 4 = 28 columns):
├── {type}_count, walk_min, cycle_min, drive_min

Green Premium (4 features × 12 = 48 columns):
├── park/forest/beach/nature_reserve
├── Size-tiered: any, 20k, 2m, 20m

Blue Premium (3 features × 8 = 24 columns):
├── lake/coastline/river

Buildings (4 columns):
├── building_count, avg_height, avg_floors, density
```

### Column Breakdown

| Section | Columns |
|---------|---------|
| **POI Level-3 (1,081 × 5)** | **5,405** |
| POI Top-Level (22 × 1) | 22 |
| Land Use | 78 |
| Water | 60 |
| Infrastructure | 60 |
| Roads | 15 |
| Transit | 28 |
| Green Premium | 48 |
| Blue Premium | 24 |
| Buildings | 4 |
| h3_index | 1 |
| **TOTAL** | **5,745** |

---

## Cost Breakdown

### Compute (m8i.96xlarge)

| Mode | Hourly | Runtime | Cost |
|------|--------|---------|------|
| **On-Demand** | $20.32 | ~8 hr | **~$165** |

*Why ~8 hours?* 
- 1,081 Level-3 categories = 2.8× more propagation than 596 Level-2
- **Extended k-rings:** k=25 for Res 10 (2.5×), k=20 for Res 8 (2×) 
- Memory-safe batching (100 cats/batch) adds ~10% overhead for temp parquet I/O
- DuckDB final merge per chunk: ~10 seconds (JOIN 12 parquets)

### Storage

| Item | Size | Rate | Cost |
|------|------|------|------|
| EBS scratch (build) | 8 TB | $0.08/GB-mo | ~$1/hr → **~$5** |
| **Hetzner Storage Box** | 10 TB | €25/mo | **€25/mo** ✅ |

### Output Size

| Resolution | Hexes | Est. Size |
|------------|-------|-----------|
| Res 5 | ~500K | ~50 MB |
| Res 8 | ~180M | ~500 GB |
| Res 10 | ~9B | ~2.5 TB |
| **TOTAL** | | **~3 TB** |

*Note: Res 11 (~59B hexes, ~3 TB) removed - too granular with diminishing returns.*

### Total Cost

| Item | Cost |
|------|------|
| Compute (on-demand) | ~$100 |
| EBS storage (build) | ~$5 |
| **Build Total** | **~$105** |
| Storage (Hetzner 10TB) | €25/mo |

*Transfer to Hetzner: rsync over SSH, included in Hetzner box.*

---

## Geographic Chunks (50 regions)

```
TIER 1 - Major Economies (GDP $1T+)
├── 🇺🇸 USA-West, USA-Central, USA-East, USA-Alaska, USA-Hawaii
├── 🇨🇳 China-North, China-East, China-South, China-West, China-Central
├── 🇩🇪 Germany
├── 🇯🇵 Japan
├── 🇮🇳 India-North, India-South, India-East, India-West
├── 🇬🇧 UK
├── 🇫🇷 France
├── 🇮🇹 Italy
└── 🇨🇦 Canada-West, Canada-Central, Canada-East

TIER 2 - Large Economies (GDP $500B-1T)
├── 🇧🇷 Brazil-North, Brazil-South, Brazil-East, Brazil-West, Brazil-Central
├── 🇷🇺 Russia-West, Russia-Central, Russia-East, Russia-Far-East
├── 🇲🇽 Mexico
├── 🇰🇷 South Korea
├── 🇦🇺 Australia-East, Australia-West, Australia-Central
├── 🇪🇸 Spain
└── 🇮🇩 Indonesia-West, Indonesia-Central, Indonesia-East

TIER 3 - Medium Economies (bundled)
├── Western Europe (NL, BE, CH, AT, SE, NO, DK, IE)
├── Eastern Europe (PL, CZ, RO, HU, etc.)
├── Middle East (SA, AE, IL, TR, etc.)
└── Southeast Asia (TH, VN, MY, SG, PH)

TIER 4 - Rest of World (bundled)
├── Africa-North, Africa-West, Africa-East, Africa-South
├── South America (excl. Brazil)
├── Central Asia
└── Oceania (excl. Australia)
```

---

## Memory-Safe Parallelization (Critical!)

### ⚠️ Risk 1: The "Fork Bomb"

Running 384 Python processes naively would crash the instance:
```
BAD:  Load 30GB dataframe → spawn 384 processes → Linux copies 30GB × 384 = 11TB (OOM!)
GOOD: Load 30GB → extract hex LISTS → pass lists to workers → workers build results
```

### ⚠️ Risk 2: Dict Bloat with 1,000+ Keys

Python dicts have per-key overhead. Building one dict with 1,081 category columns × 1M hexes:
```
BAD:  matrix = {hex: {cat1_walk: 0, cat1_cycle: 0, ...1,081 categories...}} 
      → Each hex has ~4,000 keys → ~4KB overhead/hex → 4GB just for overhead!
      
GOOD: Process in batches of 100 categories → write temp parquet → clear RAM → repeat
      → Final merge with DuckDB join (disk-based, not RAM)
```

### The Strategy: Sequential Chunks, Batched Categories

```
┌─────────────────────────────────────────────────────────────────────────┐
│                 MEMORY-SAFE BATCHED ARCHITECTURE                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  for CHUNK in 50_chunks:                    # SEQUENTIAL (one at a time)│
│  │                                                                      │
│  │   ┌──────────────────────────────────────────────────────────────┐  │
│  │   │ Load chunk POI data (~30GB)                                  │  │
│  │   │ Extract: {category: [hex_list]} for 1,081 categories         │  │
│  │   └──────────────────────────────────────────────────────────────┘  │
│  │                              │                                       │
│  │                              ▼                                       │
│  │   ┌──────────────────────────────────────────────────────────────┐  │
│  │   │ BATCH 0: Base Metrics (land use, water, buildings, counts)   │  │
│  │   │ → Write chunk_X_batch_000.parquet → Clear RAM                │  │
│  │   └──────────────────────────────────────────────────────────────┘  │
│  │                              │                                       │
│  │                              ▼                                       │
│  │   ┌──────────────────────────────────────────────────────────────┐  │
│  │   │ for BATCH in 11_batches:    # Categories 1-100, 101-200, ... │  │
│  │   │                                                               │  │
│  │   │   ProcessPoolExecutor(max_workers=380)                        │  │
│  │   │   ┌─────────┐ ┌─────────┐ ┌─────────┐     ┌─────────┐        │  │
│  │   │   │ cat_1   │ │ cat_2   │ │ cat_3   │ ... │ cat_100 │ × 100  │  │
│  │   │   │ worker  │ │ worker  │ │ worker  │     │ worker  │        │  │
│  │   │   └────┬────┘ └────┬────┘ └────┬────┘     └────┬────┘        │  │
│  │   │        └───────────┴───────────┴───────────────┘              │  │
│  │   │                          │                                    │  │
│  │   │   → Merge batch results → Write chunk_X_batch_N.parquet      │  │
│  │   │   → Clear batch dict from RAM                                │  │
│  │   │                                                               │  │
│  │   └──────────────────────────────────────────────────────────────┘  │
│  │                              │                                       │
│  │                              ▼                                       │
│  │   ┌──────────────────────────────────────────────────────────────┐  │
│  │   │ FINAL MERGE: DuckDB joins 12 batch parquets                  │  │
│  │   │                                                               │  │
│  │   │ SELECT b0.*, b1.* EXCLUDE(h3_index), b2.* EXCLUDE(h3_index)..│  │
│  │   │ FROM batch_000 b0                                            │  │
│  │   │ LEFT JOIN batch_001 b1 ON b0.h3_index = b1.h3_index          │  │
│  │   │ LEFT JOIN batch_002 b2 ON b0.h3_index = b2.h3_index          │  │
│  │   │ ...                                                          │  │
│  │   │                                                               │  │
│  │   │ → Write chunk_X_resY.parquet                                 │  │
│  │   │ → Delete temp batch files                                    │  │
│  │   │ → Update checkpoint                                          │  │
│  │   └──────────────────────────────────────────────────────────────┘  │
│  │                                                                      │
│  └─► next chunk                                                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Phase 1: DuckDB Hex Fill
```
50 geographic chunks processed in parallel
├── Each chunk: 1 DuckDB instance
├── 384 vCPUs / 50 chunks = ~7 vCPUs per chunk
├── Memory: 1.5TB / 50 = ~30GB per chunk
└── Time: ~25 minutes (I/O bound, 100Gbps helps)
```

### Phase 2: Python K-Ring Propagation
```
For each chunk (SEQUENTIAL):
├── Load chunk's POI hex data (~30GB)
├── Extract hex lists per category (light)
├── ProcessPoolExecutor: 380 workers process 596 categories
├── Each worker receives: (category_name, [hex_ids]) ← SMALL!
├── Workers DON'T copy the full dataframe
├── Merge results, save, unload
└── Time per chunk: ~40 seconds

50 chunks × 40 seconds = ~35 minutes total
```

### Phase 3: Python Edge Propagation
```
For each chunk:
├── Load polygon hex fills
├── Find edge hexes (parallel across polygons)
├── Propagate from edges
└── Time per chunk: ~15 seconds

50 chunks × 15 seconds = ~12 minutes total
```

### Phase 4: Merge
```
For each resolution:
├── UNION ALL 50 chunk files
├── Write single compressed parquet
└── Time: ~2 minutes per resolution

4 resolutions × 2 minutes = ~8 minutes total
```

---

## Travel Time Calculations

### K-Ring (POIs → Nearby Hexes)

```python
# Edge lengths per resolution
H3_EDGE_LENGTHS = {
    5: 8544,   # 8.5 km
    8: 461,    # 461 m
    10: 66,    # 66 m
    11: 45,    # 45 m
}

# Travel speeds (m/min)
TRAVEL_SPEEDS = {
    'walk': 83,    # 5 km/h
    'cycle': 250,  # 15 km/h
    'drive': 833,  # 50 km/h
}

# At Res 11 (45m edge), k=10 reaches:
walk_range  = 10 * 45 / 83  = 5.4 minutes
cycle_range = 10 * 45 / 250 = 1.8 minutes
drive_range = 10 * 45 / 833 = 0.5 minutes

# At Res 8 (461m edge), k=10 reaches:
walk_range  = 10 * 461 / 83  = 55 minutes
cycle_range = 10 * 461 / 250 = 18 minutes
drive_range = 10 * 461 / 833 = 5.5 minutes
```

### Resolution-Specific K-Rings & Decay

```python
# Extended k-rings for better coverage at key resolutions
K_RING_CONFIG = {
    5:  {'max_k': 10, 'decay_knee': 7},   # 8.5km edge → 85km range
    8:  {'max_k': 20, 'decay_knee': 15},  # 461m edge → 9.2km (90min walk)
    10: {'max_k': 25, 'decay_knee': 20},  # 66m edge → 1.65km (20min walk)
    11: {'max_k': 10, 'decay_knee': 7},   # 45m edge → 450m (5min walk)
}

def get_decay_score(k: int, resolution: int) -> float:
    """
    Two-phase linear decay with resolution-specific knee points.
    
    Res 8 (k=20, knee=15):  k=0→10, k=15→1, k=20→0
    Res 10 (k=25, knee=20): k=0→10, k=20→1, k=25→0
    """
    config = K_RING_CONFIG.get(resolution, {'max_k': 10, 'decay_knee': 7})
    max_k = config['max_k']
    knee = config['decay_knee']
    
    if k == 0:
        return 10.0
    elif k <= knee:
        return 10.0 - (9.0 * k / knee)
    elif k <= max_k:
        return (max_k - k) / (max_k - knee)
    else:
        return 0.0

# Coverage per Resolution:
# Res 5:  k=10 × 8.5km  = 85 km  (regional)
# Res 8:  k=20 × 461m   = 9.2 km (city-wide, ~90 min walk)
# Res 10: k=25 × 66m    = 1.65km (neighborhood, ~20 min walk)
# Res 11: k=10 × 45m    = 450m   (block-level, ~5 min walk)
```

---

## File Structure

```
backend/etl/
├── build_earth_matrix.py            # Local/single-region build (v4.1)
│
└── global/                          # ← ULTRA-MAXED Global Build
    ├── build_global_matrix.py       # Main orchestrator (1,081 POIs)
    ├── retail_intelligence_config.py# MAXED schema (5,745 columns)
    ├── geographic_chunks.py         # 50 chunk definitions
    ├── propagation/
    │   ├── __init__.py
    │   ├── kring.py                 # K-ring propagation
    │   ├── edge.py                  # Edge detection + propagation
    │   └── aggregation.py           # Resolution aggregation
    └── scripts/
        ├── launch_global_build.sh   # AWS launch (m8i.96xlarge)
        └── monitor.sh               # Progress monitoring

docs/
├── GLOBAL_MATRIX_BUILD.md           # This file (build documentation)
├── CASCADE_SEARCH.md                # Cascade search feature docs
└── RETAIL_INTELLIGENCE_V1_SCHEMA.md # Schema reference
```

---

## Launch Script

```bash
#!/bin/bash
# launch_global_build.sh

INSTANCE_TYPE="m8i.96xlarge"
AMI_ID="ami-0c55b159cbfafe1f0"  # Amazon Linux 2
SPOT_PRICE="7.00"  # ~35% of on-demand
VOLUME_SIZE="3000"  # 3TB

# Request spot instance
aws ec2 run-instances \
    --instance-type $INSTANCE_TYPE \
    --image-id $AMI_ID \
    --instance-market-options '{"MarketType":"spot","SpotOptions":{"MaxPrice":"'$SPOT_PRICE'"}}' \
    --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":'$VOLUME_SIZE',"VolumeType":"gp3","Iops":16000,"Throughput":1000}}]' \
    --user-data file://setup_instance.sh \
    --iam-instance-profile Name=earth-matrix-builder \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=earth-matrix-build}]'
```

---

## Checkpoint & Resume

The build automatically checkpoints progress. If interrupted, it resumes from last checkpoint:

```json
// /tmp/earth_matrix/checkpoint.json
{
  "completed_chunks": ["USA-West", "USA-East", "Germany"],
  "completed_propagations": ["USA-West_res11", "USA-West_res10", ...],
  "phase": 2
}
```

### To Resume After Interruption:

```bash
# SSH back in and restart
ssh -i ~/.ssh/earth-matrix.pem ec2-user@<instance-ip>
cd /opt/reformia
python3 backend/etl/build_global_matrix.py

# Output: "Resuming from checkpoint: 15 chunks already done"
```

---

## Monitoring

```bash
# SSH into instance
ssh -i ~/.ssh/earth-matrix.pem ec2-user@<instance-ip>

# Watch progress
tail -f /var/log/earth_matrix.log

# Check phase status
cat /tmp/earth_matrix/checkpoint.json

# Resource usage
htop                    # CPU/memory (should see ~380 python processes)
iostat -x 1             # Disk I/O
nload                   # Network (should see ~10GB/s during Phase 1)
aws s3 ls s3://earth-matrix-output/  # Output check
```

---

## Output Files

| File | Hexes | Size | Columns |
|------|-------|------|---------|
| `earth_matrix_ultra_res5.parquet` | ~500K | ~50 MB | 5,745 |
| `earth_matrix_ultra_res8.parquet` | ~180M | ~500 GB | 5,745 |
| `earth_matrix_ultra_res10.parquet` | ~9B | ~2.5 TB | 5,745 |
| **TOTAL** | | **~3 TB** | |

---

## Summary

| Metric | Value |
|--------|-------|
| Instance | m8i.96xlarge |
| vCPUs | 384 |
| RAM | 1.5 TB |
| Network | 100 Gbps |
| **POI Categories** | **1,081 (Level-3)** |
| **Total Columns** | **5,745** |
| Runtime | ~8 hours |
| **On-Demand Cost** | **~$165** |
| **Output Size** | **~6 TB** |
| **Storage** | Hetzner 10TB @ €25/mo |

---

## Why This Works

```
The "Instance Type Matrix" Arbitrage:

r7i (Memory Optimized): You pay premium for RAM density.
    → But your task is CPU-bound (1,081 categories to propagate)
    → Those expensive RAM dollars sit idle while CPUs sweat

m8i (General Purpose): You pay for balanced RAM/CPU.
    → 30GB chunks fit easily in memory
    → You want maximum CPU Firepower per Dollar
    → 2× compute density for same memory footprint

Result:
    384 vCPUs: 1,081 categories ÷ 384 = 2.8 batches per chunk
    Extended k-rings: k=25 (Res 10), k=20 (Res 8) = ~2.5× more propagation
    50 chunks × 2.8 batches × ~100s = ~4 hours for propagation
    + Hex fill (2hr) + aggregation (2hr) = ~8 hours total
    
    $20.32/hr × 8 hr = ~$165 for THE ENTIRE PLANET
```

## What You Get

```
For $165 + €25/mo storage, you can answer:

"Where can I find a RAMEN shop within 5 min walk 
 that's also near a MATCHA CAFE and a VINTAGE STORE?"

Not just "restaurant" - the actual type.
Not just "bar" - wine_bar vs sports_bar vs rooftop_bar.
Not just "gym" - crossfit vs yoga_studio vs boxing_gym.

1,081 individual POI types × 5 metrics each = 5,405 POI columns
Every hex on the planet. 4 resolution levels.
```

---

*Last Updated: December 2024*
*Schema Version: ULTRA-MAXED v4.0 (Level-3 Granularity)*
*Instance: m8i.96xlarge (384 vCPU, 1.5TB RAM, 100Gbps)*
*Cost: ~$165 on-demand + €25/mo Hetzner storage*
*Output: ~6 TB, 5,745 columns*
I We I 