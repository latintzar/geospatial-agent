#!/usr/bin/env python3
"""
Earth Matrix Benchmarking Utilities
====================================

Comprehensive benchmarking for cost extrapolation from test runs.

Features:
    - ResourceMonitor: Background thread sampling CPU/RAM/Disk/Network
    - measure_task(): Context manager for phase timing
    - log_metric(): Business metrics logger
    - estimate_global_cost(): Cost extrapolation from test data
    - track_s3_egress(): Overture S3 data transfer tracking

Usage:
    from utils_benchmark import ResourceMonitor, measure_task, log_metric, BenchmarkContext
    
    with BenchmarkContext("london_test") as ctx:
        with measure_task("Phase 1: Hex Fill"):
            # ... do work ...
            log_metric("hex_count", 15000, "hexes")

Author: Leo ETL System
"""

import csv
import json
import os
import psutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

log = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Default output directory for benchmarks
BENCHMARK_DIR = Path("benchmarks")

# Sampling interval for background monitor (seconds)
SAMPLE_INTERVAL = 1.0

# S3 pricing (Overture Maps is in us-west-2)
S3_EGRESS_COST_PER_TB = 5.0  # $5/TB for S3 data transfer

# EC2 pricing (m8i.96xlarge)
EC2_HOURLY_COST = 20.32  # On-demand price

# Geographic constants
HOXTON_AREA_KM2 = 4.25
GREATER_LONDON_AREA_KM2 = 1572
GLOBAL_INHABITED_LAND_KM2 = 60_000_000  # ~60M km² inhabited


# =============================================================================
# RESOURCE MONITOR (Background Thread)
# =============================================================================

class ResourceMonitor:
    """
    Background thread that continuously monitors system resources.
    
    Samples every SAMPLE_INTERVAL seconds and logs:
        - CPU usage (%)
        - RAM usage (GB)
        - Disk read/write (MB/s)
        - Network sent/recv (MB/s)
    
    Usage:
        monitor = ResourceMonitor(output_dir="benchmarks")
        monitor.start()
        # ... do work ...
        summary = monitor.stop()
    """
    
    def __init__(
        self, 
        output_dir: Path = BENCHMARK_DIR,
        sample_interval: float = SAMPLE_INTERVAL,
    ):
        self.output_dir = Path(output_dir)
        self.sample_interval = sample_interval
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.samples: List[Dict] = []
        self.process = psutil.Process()
        self.csv_file: Optional[Path] = None
        self.csv_writer = None
        self._file_handle = None
        
        # For disk/network delta calculations
        self._last_disk_io = None
        self._last_net_io = None
        self._last_sample_time = None
        self._start_time = None
        
    def start(self):
        """Start the background monitoring thread."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.csv_file = self.output_dir / "system_metrics.csv"
        
        # Initialize CSV
        self._file_handle = open(self.csv_file, 'w', newline='')
        self.csv_writer = csv.DictWriter(self._file_handle, fieldnames=[
            'timestamp', 'elapsed_s', 'cpu_percent', 'ram_gb', 'ram_percent',
            'disk_read_mb_s', 'disk_write_mb_s', 'net_sent_mb_s', 'net_recv_mb_s'
        ])
        self.csv_writer.writeheader()
        
        # Initialize baseline readings
        self._last_disk_io = psutil.disk_io_counters()
        self._last_net_io = psutil.net_io_counters()
        self._last_sample_time = time.time()
        self._start_time = time.time()
        
        self.running = True
        self.samples = []
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        log.info(f"ResourceMonitor started, logging to {self.csv_file}")
        
    def stop(self) -> Dict:
        """Stop monitoring and return summary statistics."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        if self._file_handle:
            self._file_handle.close()
        
        summary = self.get_summary()
        log.info(f"ResourceMonitor stopped. {len(self.samples)} samples collected.")
        return summary
        
    def _monitor_loop(self):
        """Main monitoring loop (runs in background thread)."""
        while self.running:
            try:
                sample = self._collect_sample()
                self.samples.append(sample)
                self.csv_writer.writerow(sample)
                self._file_handle.flush()
            except Exception as e:
                log.debug(f"Monitor sample failed: {e}")
            time.sleep(self.sample_interval)
            
    def _collect_sample(self) -> Dict:
        """Collect a single resource sample."""
        now = time.time()
        elapsed = now - self._start_time
        delta_t = now - self._last_sample_time
        
        # CPU (process-level)
        cpu_percent = self.process.cpu_percent()
        
        # RAM
        mem = self.process.memory_info()
        ram_gb = mem.rss / (1024 ** 3)
        ram_percent = self.process.memory_percent()
        
        # Disk I/O (system-wide, since process-level isn't reliable)
        disk_io = psutil.disk_io_counters()
        if self._last_disk_io and delta_t > 0:
            disk_read_mb_s = (disk_io.read_bytes - self._last_disk_io.read_bytes) / (1024**2) / delta_t
            disk_write_mb_s = (disk_io.write_bytes - self._last_disk_io.write_bytes) / (1024**2) / delta_t
        else:
            disk_read_mb_s = 0
            disk_write_mb_s = 0
        self._last_disk_io = disk_io
        
        # Network I/O
        net_io = psutil.net_io_counters()
        if self._last_net_io and delta_t > 0:
            net_sent_mb_s = (net_io.bytes_sent - self._last_net_io.bytes_sent) / (1024**2) / delta_t
            net_recv_mb_s = (net_io.bytes_recv - self._last_net_io.bytes_recv) / (1024**2) / delta_t
        else:
            net_sent_mb_s = 0
            net_recv_mb_s = 0
        self._last_net_io = net_io
        
        self._last_sample_time = now
        
        return {
            'timestamp': datetime.now().isoformat(),
            'elapsed_s': round(elapsed, 2),
            'cpu_percent': round(cpu_percent, 1),
            'ram_gb': round(ram_gb, 2),
            'ram_percent': round(ram_percent, 1),
            'disk_read_mb_s': round(disk_read_mb_s, 2),
            'disk_write_mb_s': round(disk_write_mb_s, 2),
            'net_sent_mb_s': round(net_sent_mb_s, 2),
            'net_recv_mb_s': round(net_recv_mb_s, 2),
        }
        
    def get_summary(self) -> Dict:
        """Calculate summary statistics from all samples."""
        if not self.samples:
            return {}
        
        return {
            'sample_count': len(self.samples),
            'duration_s': self.samples[-1]['elapsed_s'] if self.samples else 0,
            'cpu_avg_percent': sum(s['cpu_percent'] for s in self.samples) / len(self.samples),
            'cpu_max_percent': max(s['cpu_percent'] for s in self.samples),
            'ram_avg_gb': sum(s['ram_gb'] for s in self.samples) / len(self.samples),
            'ram_peak_gb': max(s['ram_gb'] for s in self.samples),
            'disk_read_total_mb': sum(s['disk_read_mb_s'] * self.sample_interval for s in self.samples),
            'disk_write_total_mb': sum(s['disk_write_mb_s'] * self.sample_interval for s in self.samples),
            'net_recv_total_mb': sum(s['net_recv_mb_s'] * self.sample_interval for s in self.samples),
            'net_sent_total_mb': sum(s['net_sent_mb_s'] * self.sample_interval for s in self.samples),
        }


# =============================================================================
# TASK TIMER (Context Manager)
# =============================================================================

@dataclass
class TaskMetrics:
    """Metrics collected for a single task."""
    task_name: str
    start_time: str = ""
    end_time: str = ""
    duration_s: float = 0.0
    ram_start_gb: float = 0.0
    ram_end_gb: float = 0.0
    ram_peak_gb: float = 0.0
    cpu_avg_percent: float = 0.0
    success: bool = True
    error: str = ""
    

# Global task metrics storage (thread-safe via GIL for simple appends)
_task_metrics: List[TaskMetrics] = []
_current_task: Optional[TaskMetrics] = None
_task_samples: List[Dict] = []


@contextmanager
def measure_task(task_name: str):
    """
    Context manager for measuring task execution.
    
    Usage:
        with measure_task("Phase 1: Hex Fill"):
            # ... do work ...
    
    Logs:
        - Start/End time
        - Duration
        - Peak RAM during task
        - Average CPU during task
    """
    global _current_task, _task_samples
    
    process = psutil.Process()
    
    # Initialize task
    task = TaskMetrics(task_name=task_name)
    task.start_time = datetime.now().isoformat()
    task.ram_start_gb = process.memory_info().rss / (1024 ** 3)
    
    _current_task = task
    _task_samples = []
    
    start = time.time()
    
    # Start mini-monitor for this task
    def sample_during_task():
        while _current_task is task:
            try:
                _task_samples.append({
                    'ram_gb': process.memory_info().rss / (1024 ** 3),
                    'cpu_percent': process.cpu_percent(),
                })
            except:
                pass
            time.sleep(0.5)
    
    sampler = threading.Thread(target=sample_during_task, daemon=True)
    sampler.start()
    
    log.info(f"[TASK START] {task_name}")
    
    try:
        yield task
        task.success = True
    except Exception as e:
        task.success = False
        task.error = str(e)
        raise
    finally:
        # Finalize task
        task.end_time = datetime.now().isoformat()
        task.duration_s = time.time() - start
        task.ram_end_gb = process.memory_info().rss / (1024 ** 3)
        
        if _task_samples:
            task.ram_peak_gb = max(s['ram_gb'] for s in _task_samples)
            task.cpu_avg_percent = sum(s['cpu_percent'] for s in _task_samples) / len(_task_samples)
        else:
            task.ram_peak_gb = task.ram_end_gb
            task.cpu_avg_percent = 0
        
        _task_metrics.append(task)
        _current_task = None
        
        status = "✓" if task.success else "✗"
        log.info(f"[TASK END] {status} {task_name}: {task.duration_s:.2f}s, Peak RAM: {task.ram_peak_gb:.2f}GB")


# =============================================================================
# BUSINESS METRICS LOGGER
# =============================================================================

@dataclass
class BusinessMetric:
    """A single business metric."""
    name: str
    value: Any
    unit: str
    timestamp: str = ""
    phase: str = ""


# Global business metrics storage
_business_metrics: List[BusinessMetric] = []


def log_metric(name: str, value: Any, unit: str = "", phase: str = ""):
    """
    Log a business metric.
    
    Usage:
        log_metric("hex_count", 15000, "hexes")
        log_metric("poi_count", 250000, "pois", phase="extraction")
        log_metric("s3_bytes_read", 1024*1024*500, "bytes")
    """
    metric = BusinessMetric(
        name=name,
        value=value,
        unit=unit,
        timestamp=datetime.now().isoformat(),
        phase=phase,
    )
    _business_metrics.append(metric)
    log.info(f"[METRIC] {name}: {value:,} {unit}")


def get_metric(name: str) -> Optional[Any]:
    """Get the most recent value of a metric by name."""
    for m in reversed(_business_metrics):
        if m.name == name:
            return m.value
    return None


# =============================================================================
# S3 EGRESS TRACKING
# =============================================================================

@dataclass
class S3EgressTracker:
    """
    Tracks S3 data transfer for cost estimation.
    
    Overture Maps charges $5/TB for data transfer from S3.
    """
    total_bytes: int = 0
    queries: List[Dict] = field(default_factory=list)
    
    def log_query(self, description: str, bytes_read: int):
        """Log an S3 query and its data transfer."""
        self.total_bytes += bytes_read
        self.queries.append({
            'timestamp': datetime.now().isoformat(),
            'description': description,
            'bytes': bytes_read,
            'mb': bytes_read / (1024**2),
        })
        log_metric("s3_bytes_read", bytes_read, "bytes", phase=description)
        
    @property
    def total_tb(self) -> float:
        return self.total_bytes / (1024**4)
    
    @property
    def estimated_cost(self) -> float:
        return self.total_tb * S3_EGRESS_COST_PER_TB
    
    def get_summary(self) -> Dict:
        return {
            'total_bytes': self.total_bytes,
            'total_mb': self.total_bytes / (1024**2),
            'total_gb': self.total_bytes / (1024**3),
            'total_tb': self.total_tb,
            'estimated_cost_usd': self.estimated_cost,
            'query_count': len(self.queries),
        }


# Global S3 tracker instance
s3_tracker = S3EgressTracker()


def estimate_s3_read_size(row_count: int, avg_row_bytes: int = 500) -> int:
    """
    Estimate S3 bytes read based on row count.
    
    This is approximate - Parquet compression and predicate pushdown
    make exact calculation difficult. Use avg_row_bytes as tuning param.
    
    Args:
        row_count: Number of rows read
        avg_row_bytes: Average bytes per row (varies by table)
        
    Returns:
        Estimated bytes read from S3
    """
    # Parquet typically compresses 3-5x, and predicate pushdown
    # means we often read only 10-30% of data. Use conservative estimate.
    return int(row_count * avg_row_bytes * 0.3)


# =============================================================================
# COST EXTRAPOLATION - CHUNK-BASED PARALLELISM MODEL
# =============================================================================

# Global build constants (from geographic_chunks.py)
TOTAL_GLOBAL_CHUNKS = 350  # Countries/regions to process
EC2_CONCURRENT_CHUNKS = 35  # Bounded parallelism on m8i.96xlarge (350 threads / 10 per chunk)
THREADS_PER_CHUNK_GLOBAL = 10  # Threads per chunk on EC2

# Size categories for chunks (relative to Greater London = 1.0)
CHUNK_SIZE_DISTRIBUTION = {
    'tiny': {'count': 100, 'relative_size': 0.1},      # Small islands, city-states
    'small': {'count': 80, 'relative_size': 0.3},       # Small countries
    'medium': {'count': 100, 'relative_size': 1.0},     # Medium countries (~London size)
    'large': {'count': 50, 'relative_size': 3.0},       # Large countries
    'huge': {'count': 20, 'relative_size': 10.0},       # USA, China, Russia, etc.
}


def estimate_global_cost(
    test_metrics: Dict,
    test_region: str = "hoxton",
    test_area_km2: float = HOXTON_AREA_KM2,
    max_concurrent_chunks: int = EC2_CONCURRENT_CHUNKS,
) -> Dict:
    """
    Extrapolate global build cost using CHUNK-BASED PARALLELISM model.
    
    This matches the actual build architecture:
    - Global = 350 independent chunks processed in parallel
    - EC2 runs up to 35 chunks concurrently (bounded parallelism)
    - Each chunk takes roughly similar time (normalized by complexity)
    
    Args:
        test_metrics: Dict with:
            - duration_s: Total test duration
            - phase2_duration_s: Phase 2 (propagation) time
            - hex_count_res8/10/11: Hexes generated per resolution
            - output_size_mb: Output file size
        test_region: Name of test region (hoxton, greater_london, etc.)
        test_area_km2: Area of test region in km²
        max_concurrent_chunks: Concurrent chunks on target instance
        
    Returns:
        Dict with cost estimates and breakdown
    """
    test_duration_s = test_metrics.get('duration_s', 0)
    phase2_duration_s = test_metrics.get('phase2_duration_s', test_duration_s * 0.7)  # Assume 70% is propagation
    
    # Determine test region complexity multiplier
    # Key insight: For very small test areas, fixed overhead dominates
    # We need to estimate the "actual work time" vs "overhead time"
    
    if test_region.lower() == "hoxton":
        # Hoxton is very small (~4 km²) - mostly overhead
        # Estimated: 60% overhead, 40% actual work
        overhead_fraction = 0.6
        actual_work_time_s = test_duration_s * (1 - overhead_fraction)
        
        # Scale actual work to medium chunk size
        test_to_chunk_multiplier = GREATER_LONDON_AREA_KM2 / HOXTON_AREA_KM2  # ~370x
        # Use log scaling for very small → medium extrapolation
        # (going from 100 hexes to 50k hexes doesn't take 500x longer)
        scaling_factor = min(test_to_chunk_multiplier ** 0.3, 20)  # Cap at 20x
        base_chunk_time_s = actual_work_time_s * scaling_factor + (test_duration_s * overhead_fraction)
        
    elif test_region.lower() == "greater_london":
        # Greater London IS a medium chunk - direct comparison
        test_to_chunk_multiplier = 1.0
        base_chunk_time_s = test_duration_s
        
    else:
        # Unknown region - use conservative scaling
        test_to_chunk_multiplier = GREATER_LONDON_AREA_KM2 / test_area_km2
        if test_to_chunk_multiplier > 10:
            base_chunk_time_s = test_duration_s * (test_to_chunk_multiplier ** 0.3)
        else:
            base_chunk_time_s = test_duration_s * test_to_chunk_multiplier
    
    # Calculate weighted average chunk time based on size distribution
    total_chunk_work = 0
    total_chunks = 0
    for category, info in CHUNK_SIZE_DISTRIBUTION.items():
        chunk_time = base_chunk_time_s * info['relative_size']
        total_chunk_work += chunk_time * info['count']
        total_chunks += info['count']
    
    average_chunk_time_s = total_chunk_work / total_chunks
    
    # Total serial work (if processing one chunk at a time)
    total_serial_time_s = total_chunk_work
    
    # Parallel time with bounded concurrency
    # Chunks complete in waves: ceil(350/35) = 10 waves
    waves = (TOTAL_GLOBAL_CHUNKS + max_concurrent_chunks - 1) // max_concurrent_chunks
    
    # Each wave takes as long as the slowest chunk in that wave
    # Approximate as: average_chunk_time × wave_overhead_factor
    wave_overhead = 1.3  # 30% overhead for load imbalance and I/O
    parallel_global_time_s = waves * average_chunk_time_s * wave_overhead
    parallel_global_time_h = parallel_global_time_s / 3600
    
    # Compute cost
    compute_cost = parallel_global_time_h * EC2_HOURLY_COST
    
    # S3 cost extrapolation (based on network traffic)
    # Overture global ~800GB compressed, we read ~2x for redundancy/retries
    s3_bytes_test = test_metrics.get('s3_bytes_read', 0)
    net_recv_mb = test_metrics.get('net_recv_total_mb', 350)  # From resource monitor
    
    # Scale network to global
    global_s3_estimate_gb = 800 * 2  # ~1.6TB for global (conservative)
    s3_tb_global = global_s3_estimate_gb / 1024
    s3_cost = s3_tb_global * S3_EGRESS_COST_PER_TB
    
    # Storage cost (Hetzner 10TB @ €25/mo)
    storage_cost_monthly = 25  # EUR
    
    # Total
    total_cost = compute_cost + s3_cost
    
    # Safety margin for unexpected overhead
    total_cost_with_margin = total_cost * 1.2  # 20% safety buffer
    
    return {
        'test_region': {
            'name': test_region,
            'area_km2': test_area_km2,
            'duration_s': test_duration_s,
            'phase2_duration_s': phase2_duration_s,
            'output_size_mb': test_metrics.get('output_size_mb', 0),
        },
        'chunk_model': {
            'total_global_chunks': TOTAL_GLOBAL_CHUNKS,
            'concurrent_chunks': max_concurrent_chunks,
            'waves_required': waves,
            'base_chunk_time_s': round(base_chunk_time_s, 1),
            'average_chunk_time_s': round(average_chunk_time_s, 1),
            'test_to_chunk_multiplier': round(test_to_chunk_multiplier, 2),
        },
        'time_estimates': {
            'total_serial_hours': round(total_serial_time_s / 3600, 2),
            'parallel_global_hours': round(parallel_global_time_h, 2),
            'parallel_global_minutes': round(parallel_global_time_h * 60, 1),
            'wave_overhead_factor': wave_overhead,
        },
        'cost_breakdown': {
            'compute_usd': round(compute_cost, 2),
            's3_egress_usd': round(s3_cost, 2),
            'subtotal_usd': round(total_cost, 2),
            'safety_margin_20pct': round(total_cost * 0.2, 2),
            'total_with_margin_usd': round(total_cost_with_margin, 2),
            'storage_monthly_eur': storage_cost_monthly,
        },
        'assumptions': {
            'ec2_instance': 'm8i.96xlarge',
            'ec2_hourly_usd': EC2_HOURLY_COST,
            's3_per_tb_usd': S3_EGRESS_COST_PER_TB,
            's3_global_estimate_tb': round(s3_tb_global, 2),
            'chunk_size_distribution': CHUNK_SIZE_DISTRIBUTION,
        },
        'confidence': {
            'level': 'medium' if test_region == 'greater_london' else 'low',
            'note': 'Run Greater London test on EC2 for high confidence estimate',
        }
    }


# =============================================================================
# BENCHMARK CONTEXT (Combines Everything)
# =============================================================================

class BenchmarkContext:
    """
    Main context manager for running benchmarked builds.
    
    Usage:
        with BenchmarkContext("hoxton_test") as ctx:
            with measure_task("Phase 1"):
                # ... work ...
            log_metric("hex_count", 5000, "hexes")
        
        # Results saved to benchmarks/hoxton_test/
    """
    
    def __init__(self, run_name: str, output_dir: Path = BENCHMARK_DIR, test_region: str = "hoxton"):
        self.run_name = run_name
        self.test_region = test_region
        self.output_dir = Path(output_dir) / run_name
        self.monitor: Optional[ResourceMonitor] = None
        self.start_time: float = 0
        
    def __enter__(self):
        global _task_metrics, _business_metrics, s3_tracker
        
        # Reset global state
        _task_metrics = []
        _business_metrics = []
        s3_tracker = S3EgressTracker()
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Start resource monitor
        self.monitor = ResourceMonitor(output_dir=self.output_dir)
        self.monitor.start()
        
        self.start_time = time.time()
        log.info(f"[BENCHMARK] Started: {self.run_name}")
        
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Stop monitor
        resource_summary = self.monitor.stop() if self.monitor else {}
        
        total_duration = time.time() - self.start_time
        
        # Save task metrics
        task_data = [asdict(t) for t in _task_metrics]
        with open(self.output_dir / "task_metrics.json", 'w') as f:
            json.dump(task_data, f, indent=2)
        
        # Save business metrics
        business_data = [asdict(m) for m in _business_metrics]
        with open(self.output_dir / "business_metrics.json", 'w') as f:
            json.dump(business_data, f, indent=2)
        
        # Save S3 tracking
        with open(self.output_dir / "s3_egress.json", 'w') as f:
            json.dump(s3_tracker.get_summary(), f, indent=2)
        
        # Calculate and save cost extrapolation
        # Get test region info
        region_info = TEST_REGIONS.get(self.test_region, TEST_REGIONS['hoxton'])
        
        # Get phase 2 duration from task metrics
        phase2_duration = 0
        for task in _task_metrics:
            if 'phase 2' in task.task_name.lower() or 'propagation' in task.task_name.lower():
                phase2_duration = task.duration_s
                break
        
        # Get output size from business metrics
        output_size_mb = get_metric('total_output_size_mb') or 0
        
        test_metrics = {
            'duration_s': total_duration,
            'phase2_duration_s': phase2_duration or total_duration * 0.7,
            'output_size_mb': output_size_mb,
            's3_bytes_read': s3_tracker.total_bytes,
            'net_recv_total_mb': resource_summary.get('net_recv_total_mb', 0),
        }
        extrapolation = estimate_global_cost(
            test_metrics,
            test_region=self.test_region,
            test_area_km2=region_info['area_km2'],
        )
        with open(self.output_dir / "cost_extrapolation.json", 'w') as f:
            json.dump(extrapolation, f, indent=2)
        
        # Get cost from new structure
        total_cost = extrapolation['cost_breakdown']['total_with_margin_usd']
        
        # Save summary
        summary = {
            'run_name': self.run_name,
            'test_region': self.test_region,
            'start_time': datetime.fromtimestamp(self.start_time).isoformat(),
            'end_time': datetime.now().isoformat(),
            'total_duration_s': total_duration,
            'resource_summary': resource_summary,
            's3_summary': s3_tracker.get_summary(),
            'task_count': len(_task_metrics),
            'metric_count': len(_business_metrics),
            'extrapolated_global_cost_usd': total_cost,
        }
        with open(self.output_dir / "summary.json", 'w') as f:
            json.dump(summary, f, indent=2)
        
        log.info(f"[BENCHMARK] Complete: {self.run_name}")
        log.info(f"  Duration: {total_duration:.1f}s")
        log.info(f"  Output: {self.output_dir}")
        log.info(f"  Extrapolated global cost: ${total_cost:.2f}")


# =============================================================================
# TEST MODE CONFIGURATION
# =============================================================================

# Test region bounding boxes
TEST_REGIONS = {
    'hoxton': {
        'name': 'Hoxton, London',
        'bbox': [-0.095, 51.525, -0.070, 51.540],
        'area_km2': 4.25,
    },
    'greater_london': {
        'name': 'Greater London',
        'bbox': [-0.5103, 51.2867, 0.3340, 51.6918],
        'area_km2': 1572,
    },
    'france': {
        'name': 'France',
        'bbox': [-5.14, 41.36, 9.56, 51.09],
        'area_km2': 640679,
    },
    'uk': {
        'name': 'United Kingdom',
        'bbox': [-8.6, 49.9, 1.8, 60.9],
        'area_km2': 243610,
    },
}


def get_test_bbox(region: str = 'hoxton') -> tuple:
    """Get bounding box for a test region."""
    if region in TEST_REGIONS:
        return TEST_REGIONS[region]['bbox'], TEST_REGIONS[region]['area_km2']
    raise ValueError(f"Unknown test region: {region}. Options: {list(TEST_REGIONS.keys())}")


# =============================================================================
# MAIN (Self-test)
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    print("Testing utils_benchmark.py...")
    
    with BenchmarkContext("self_test") as ctx:
        with measure_task("Test Task 1"):
            time.sleep(0.5)
            log_metric("test_count", 100, "items")
        
        with measure_task("Test Task 2"):
            time.sleep(0.3)
            log_metric("test_size", 1024, "bytes")
            s3_tracker.log_query("test_query", 1024 * 1024 * 10)  # 10 MB
    
    print("\nTest complete! Check benchmarks/self_test/")

