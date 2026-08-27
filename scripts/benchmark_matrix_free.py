#!/usr/bin/env python3
"""Benchmark the matrix-free verifier on a feasible representative history."""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path
import platform
import resource
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from upper_engine import build_graph, sha256_file  # noqa: E402
from verify_matrix_free import (  # noqa: E402
    Certificate,
    atomic_json,
    compile_kernel,
    build_fresh_index,
    load_witness,
    run_kernel,
    scan_chunk,
    upward_weights,
)


def peak_child_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return int(value if platform.system() == "Darwin" else value * 1024)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=int, default=6)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def run(history: int, threads: int, work_dir: Path) -> dict:
    started = time.perf_counter()
    graph_dir = work_dir / f"h{history}-graph"
    build_started = time.perf_counter()
    graph = build_graph(history, graph_dir)
    build_seconds = time.perf_counter() - build_started
    states = graph_dir / "states.u64"
    state_sha = sha256_file(states)
    kernel, kernel_details = compile_kernel(work_dir)
    index, capacity, index_details = build_fresh_index(
        kernel,
        work_dir,
        states,
        history=history,
        state_count=int(graph["state_count"]),
        state_sha256=state_sha,
        kernel_source_sha256=kernel_details["source_sha256"],
        kernel_binary_sha256=kernel_details["binary_sha256"],
    )
    witness_path = work_dir / "ones-witness.npy"
    np.save(
        witness_path,
        np.ones(int(graph["state_count"]), dtype="<u4"),
        allow_pickle=False,
    )
    witness = load_witness(witness_path, int(graph["state_count"]))
    certificate = Certificate(
        history=history,
        state_count=int(graph["state_count"]),
        z=Fraction(3209, 10000),
        lambda_numerator=(1 << 64) - 1,
        lambda_denominator=1 << 32,
        witness_scale=1,
        target_numerator=824443,
        target_denominator=1_000_000,
    )
    weights = upward_weights(certificate)
    dump_path = work_dir / "oracle-transitions.u32"
    dump_started = time.perf_counter()
    dump = run_kernel(
        [
            str(kernel),
            "dump",
            str(history),
            str(states),
            str(certificate.state_count),
            str(index),
            str(capacity),
            "0",
            str(certificate.state_count),
            str(threads),
            str(dump_path),
        ],
        executable_sha256=kernel_details["binary_sha256"],
    )
    dump_seconds = time.perf_counter() - dump_started
    if dump_path.read_bytes() != (graph_dir / "transitions.u32").read_bytes():
        raise RuntimeError("independent transition dump differs from the builder")
    scan = scan_chunk(
        kernel,
        certificate=certificate,
        states=states,
        index=index,
        capacity=capacity,
        witness=witness_path,
        witness_offset=int(witness.offset),
        weights=weights,
        start=0,
        end=certificate.state_count,
        threads=threads,
        kernel_binary_sha256=kernel_details["binary_sha256"],
    )
    transitions = certificate.state_count * certificate.columns
    return {
        "schema_version": 1,
        "kind": "matrix-free-verifier-benchmark",
        "history": history,
        "states": certificate.state_count,
        "columns": certificate.columns,
        "transitions": transitions,
        "threads": threads,
        "builder_seconds": build_seconds,
        "index_seconds": index_details.get("build_seconds", 0.0),
        "oracle_dump_seconds": dump_seconds,
        "oracle_transitions_per_second": transitions / dump_seconds,
        "certificate_scan_seconds": scan["scan_seconds"],
        "certificate_transitions_per_second": transitions / scan["scan_seconds"],
        "certificate_peak_rss_bytes": scan["peak_rss_bytes"],
        "accepted_transitions": scan["accepted_transitions"],
        "rejected_transitions": scan["rejected_transitions"],
        "transition_byte_agreement": True,
        "state_sha256": state_sha,
        "builder_transition_sha256": sha256_file(graph_dir / "transitions.u32"),
        "oracle_transition_sha256": sha256_file(dump_path),
        "index_bytes": index.stat().st_size,
        "index_peak_rss_bytes": index_details.get("peak_rss_bytes"),
        "state_bytes": states.stat().st_size,
        "witness_bytes": witness_path.stat().st_size,
        "peak_child_rss_bytes": peak_child_rss_bytes(),
        "wall_seconds": time.perf_counter() - started,
        "platform": platform.platform(),
        "python": sys.version,
        "compiler": kernel_details["compiler"],
        "kernel_build_status": kernel_details["status"],
        "kernel_private_runtime_directory": kernel_details[
            "private_runtime_directory"
        ],
        "kernel_source_sha256": kernel_details["source_sha256"],
        "index_build_status": index_details["status"],
    }


def main() -> int:
    args = make_parser().parse_args()
    if args.history < 2 or args.history > 6:
        raise SystemExit("benchmark history must lie in [2,6]")
    if args.threads < 1:
        raise SystemExit("threads must be positive")
    if args.work_dir is None:
        with tempfile.TemporaryDirectory() as temporary:
            result = run(args.history, args.threads, Path(temporary))
    else:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        result = run(args.history, args.threads, args.work_dir)
    if args.output is not None:
        atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
