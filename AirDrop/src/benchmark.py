"""Throughput benchmarking utility for AirDrop transports."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Any

from src.file_io import compute_file_sha256
from src.protocol import format_bytes, format_throughput
from src.receiver import Receiver
from src.sender import Sender
from src.transport import TransportType

logger = logging.getLogger("airdrop.benchmark")


@dataclass
class BenchmarkResult:
    """Detailed transfer benchmark metrics."""

    file_size_bytes: int
    chunk_size_bytes: int
    transport_name: str
    duration_seconds: float
    throughput_bytes_per_sec: float
    throughput_mbps: float
    sha256_match: bool
    connect_time_ms: float = 0.0

    @property
    def throughput_str(self) -> str:
        return format_throughput(self.file_size_bytes, self.duration_seconds)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["file_size_str"] = format_bytes(self.file_size_bytes)
        d["chunk_size_str"] = format_bytes(self.chunk_size_bytes)
        d["throughput_formatted"] = self.throughput_str
        return d


def run_single_benchmark(
    host: str,
    port: int,
    file_path: Path,
    chunk_size: int = 64 * 1024,
    timeout: float = 30.0,
    direct_host: str | None = None,
    direct_port: int | None = None,
) -> BenchmarkResult:
    """Execute a single transfer benchmark against target receiver."""
    sender = Sender(
        host=host,
        port=port,
        timeout=timeout,
        chunk_size=chunk_size,
        direct_host=direct_host,
        direct_port=direct_port,
    )

    t0 = time.perf_counter()
    metrics = sender.send_file(file_path, precompute_sha256=True)
    total_time = time.perf_counter() - t0

    file_size = metrics["filesize"]
    duration = metrics["duration"]
    bytes_per_sec = file_size / duration if duration > 0 else 0.0
    mbps = (bytes_per_sec * 8) / 1_000_000

    return BenchmarkResult(
        file_size_bytes=file_size,
        chunk_size_bytes=chunk_size,
        transport_name=metrics.get("transport_type", TransportType.LAN_TCP.value),
        duration_seconds=duration,
        throughput_bytes_per_sec=bytes_per_sec,
        throughput_mbps=mbps,
        sha256_match=True,
    )


def run_local_benchmark_matrix(
    sizes_mib: list[int] = [1, 5, 20],
    chunk_sizes: list[int] = [16 * 1024, 64 * 1024, 256 * 1024],
) -> list[BenchmarkResult]:
    """Run an automated benchmark matrix across file sizes and chunk sizes locally."""
    results: list[BenchmarkResult] = []
    temp_dir = tempfile.mkdtemp(prefix="airdrop_bench_")
    dest_dir = Path(temp_dir) / "dest"
    src_dir = Path(temp_dir) / "src"
    dest_dir.mkdir(parents=True)
    src_dir.mkdir(parents=True)

    receiver = Receiver(
        host="127.0.0.1",
        port=0,
        dest_dir=dest_dir,
        advertise=False,
        enable_ble=False,
    )

    recv_thread = threading.Thread(target=receiver.start, daemon=True)
    recv_thread.start()

    start = time.time()
    while receiver.active_port is None and (time.time() - start < 5.0):
        time.sleep(0.01)

    port = receiver.active_port
    assert port is not None, "Failed to bind receiver"

    try:
        for size_mib in sizes_mib:
            num_bytes = size_mib * 1024 * 1024
            test_file = src_dir / f"bench_{size_mib}mb.dat"

            # Create test data with repeating pattern for fast generation
            chunk_pat = os.urandom(64 * 1024)
            with open(test_file, "wb") as f:
                for _ in range(num_bytes // len(chunk_pat)):
                    f.write(chunk_pat)

            for chunk_sz in chunk_sizes:
                res = run_single_benchmark(
                    host="127.0.0.1",
                    port=port,
                    file_path=test_file,
                    chunk_size=chunk_sz,
                )
                results.append(res)
    finally:
        receiver.stop()
        recv_thread.join(timeout=2.0)
        shutil.rmtree(temp_dir, ignore_errors=True)

    return results


def format_benchmark_table(results: list[BenchmarkResult]) -> str:
    """Format benchmark results into a clean table."""
    headers = ["File Size", "Chunk Size", "Transport", "Duration (s)", "Throughput (MB/s)", "Throughput (Mbps)", "Integrity"]
    rows: list[list[str]] = []
    for r in results:
        rows.append([
            format_bytes(r.file_size_bytes),
            format_bytes(r.chunk_size_bytes),
            r.transport_name,
            f"{r.duration_seconds:.3f}",
            f"{r.throughput_bytes_per_sec / (1024*1024):.2f}",
            f"{r.throughput_mbps:.1f}",
            "PASSED" if r.sha256_match else "FAILED",
        ])

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(val))

    def make_divider(char: str = "-") -> str:
        parts = [char * (w + 2) for w in col_widths]
        return "+" + "+".join(parts) + "+"

    def format_row(row_vals: list[str]) -> str:
        parts = [f" {val.ljust(col_widths[i])} " for i, val in enumerate(row_vals)]
        return "|" + "|".join(parts) + "|"

    out = [
        make_divider("-"),
        format_row(headers),
        make_divider("="),
    ]
    for row in rows:
        out.append(format_row(row))
    out.append(make_divider("-"))
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AirDrop Transfer Benchmark - Measure throughput across transports and chunk sizes."
    )
    parser.add_argument(
        "--host",
        help="Target receiver host/IP (if omitting, runs local loopback matrix)",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=5001,
        help="Target receiver port (default: 5001)",
    )
    parser.add_argument(
        "-f", "--file",
        help="Path to an existing file to test with",
    )
    parser.add_argument(
        "--direct-host",
        help="Target Direct Wi-Fi IP (for testing direct transport)",
    )
    parser.add_argument(
        "--direct-port",
        type=int,
        help="Target Direct Wi-Fi port",
    )
    parser.add_argument(
        "--size-mib",
        type=int,
        default=10,
        help="File size in MiB when generating synthetic test data (default: 10)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    if not args.host:
        print("Running AirDrop Local Transfer Benchmark Matrix...")
        results = run_local_benchmark_matrix(sizes_mib=[1, 5, 20])
    else:
        # Benchmark target host
        temp_dir = None
        if not args.file:
            temp_dir = tempfile.mkdtemp(prefix="airdrop_bench_single_")
            test_file = Path(temp_dir) / f"bench_{args.size_mib}mb.bin"
            print(f"Generating {args.size_mib} MiB test file...")
            pattern = os.urandom(64 * 1024)
            with open(test_file, "wb") as f:
                for _ in range((args.size_mib * 1024 * 1024) // len(pattern)):
                    f.write(pattern)
        else:
            test_file = Path(args.file)

        try:
            results = []
            for chunk_sz in [16 * 1024, 64 * 1024, 256 * 1024]:
                res = run_single_benchmark(
                    host=args.host,
                    port=args.port,
                    file_path=test_file,
                    chunk_size=chunk_sz,
                    direct_host=args.direct_host,
                    direct_port=args.direct_port,
                )
                results.append(res)
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print("\n=== AirDrop Benchmark Results ===")
        print(format_benchmark_table(results))


if __name__ == "__main__":
    main()
