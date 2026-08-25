"""Restart-safe fixed-point engine for Lueker's 2009 upper-bound method."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import tempfile
import time
from typing import Any

import numba
import numpy as np


REJECT = np.uint32(0xFFFFFFFF)
WEIGHT_SCALE = 1 << 32
WITNESS_SCALE = 1 << 26
RESERVE_BYTES = 20 * (1 << 30)
GRAPH_COUNTS = {
    2: 7,
    3: 98,
    4: 1020,
    5: 10160,
    6: 89960,
    7: 780368,
    8: 6419109,
    9: 51425006,
    10: 400253317,
}
KERNEL_VERSION = "upper-fixed-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def process_peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if platform.system() == "Darwin" else value * 1024)


def sha256_file(path: Path, chunk_size: int = 8 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_npy(path: Path, values: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            np.save(handle, values, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        digest = sha256_file(Path(temporary))
        os.replace(temporary, path)
        return digest
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def compile_graph_builder() -> Path:
    source = Path(__file__).with_name("upper_graph_builder.c")
    output = Path(__file__).with_name(".upper_graph_builder")
    if not output.exists() or output.stat().st_mtime_ns < source.stat().st_mtime_ns:
        subprocess.run(
            ["clang", "-O3", "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(output)],
            check=True,
        )
    return output


def expected_states(history: int) -> int:
    if history in GRAPH_COUNTS:
        return GRAPH_COUNTS[history]
    # A sizing hint only. The builder grows its state queue but deliberately
    # refuses a hash table above 70% load rather than silently misbehaving.
    largest_exact = max(GRAPH_COUNTS)
    return max(1024, GRAPH_COUNTS[largest_exact] * (9 ** (history - largest_exact)))


def builder_sizing_plan(history: int) -> dict[str, int | bool]:
    """Return the builder's exact allocation plan before any allocation."""

    expected = expected_states(history)
    desired_hash_slots = 2 * expected + 1
    hash_capacity = 1 << (desired_hash_slots - 1).bit_length()
    state_queue_bytes = expected * 8
    hash_bytes = hash_capacity * (8 + 4)
    return {
        "history": history,
        "expected_state_hint": expected,
        "uint32_index_preflight": expected < int(REJECT),
        "hash_capacity": hash_capacity,
        "hash_bytes": hash_bytes,
        "state_queue_bytes": state_queue_bytes,
        "planned_live_bytes": state_queue_bytes + hash_bytes,
    }


def build_graph(history: int, graph_dir: Path, *, force: bool = False) -> dict[str, Any]:
    plan = builder_sizing_plan(history)
    if not plan["uint32_index_preflight"]:
        raise ValueError(
            "builder sizing hint exceeds the uint32 successor-index format: "
            f"history={history} hint={plan['expected_state_hint']} limit={int(REJECT) - 1}"
        )
    graph_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = graph_dir / "graph.json"
    if manifest_path.exists() and not force:
        return authenticate_graph(graph_dir)
    builder = compile_graph_builder()
    transitions = graph_dir / "transitions.u32"
    states = graph_dir / "states.u64"
    transitions_partial = graph_dir / ".transitions.u32.partial"
    states_partial = graph_dir / ".states.u64.partial"
    for path in (transitions_partial, states_partial):
        path.unlink(missing_ok=True)
    started = time.perf_counter()
    completed = subprocess.run(
        [str(builder), str(history), str(expected_states(history)), str(transitions_partial), str(states_partial)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    print(completed.stdout, end="", flush=True)
    builder_fields = dict(field.split("=", 1) for field in completed.stdout.strip().split())
    state_count, state_remainder = divmod(states_partial.stat().st_size, 8)
    columns = 2 * (2 * history - 1)
    expected_transition_bytes = state_count * columns * 4
    if state_remainder or transitions_partial.stat().st_size != expected_transition_bytes:
        raise RuntimeError("graph builder produced inconsistent file sizes")
    if history in GRAPH_COUNTS and state_count != GRAPH_COUNTS[history]:
        raise RuntimeError(
            f"published state count mismatch: got {state_count}, expected {GRAPH_COUNTS[history]}"
        )
    os.replace(transitions_partial, transitions)
    os.replace(states_partial, states)
    payload = {
        "schema_version": 1,
        "kind": "lueker-upper-dense-graph",
        "kernel_version": KERNEL_VERSION,
        "created_at": utc_now(),
        "history": history,
        "state_count": state_count,
        "columns": columns,
        "reject_index": int(REJECT),
        "state_dtype": "<u8",
        "transition_dtype": "<u4",
        "states_file": states.name,
        "states_bytes": states.stat().st_size,
        "states_sha256": sha256_file(states),
        "transitions_file": transitions.name,
        "transitions_bytes": transitions.stat().st_size,
        "transitions_sha256": sha256_file(transitions),
        "build_seconds": time.perf_counter() - started,
        "builder_seconds": float(builder_fields["seconds"]),
        "builder_peak_rss_bytes": int(builder_fields["peak_rss_bytes"]),
    }
    atomic_json(manifest_path, payload)
    return payload


def authenticate_graph(graph_dir: Path) -> dict[str, Any]:
    manifest_path = graph_dir / "graph.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "lueker-upper-dense-graph":
        raise ValueError("unexpected graph kind")
    for prefix in ("states", "transitions"):
        path = graph_dir / manifest[f"{prefix}_file"]
        if path.stat().st_size != manifest[f"{prefix}_bytes"]:
            raise ValueError(f"{prefix} byte count mismatch")
        if sha256_file(path) != manifest[f"{prefix}_sha256"]:
            raise ValueError(f"{prefix} SHA-256 mismatch")
    return manifest


def load_graph(graph_dir: Path, *, authenticate: bool = True):
    manifest = authenticate_graph(graph_dir) if authenticate else json.loads(
        (graph_dir / "graph.json").read_text(encoding="utf-8")
    )
    states = np.memmap(
        graph_dir / manifest["states_file"], dtype=np.dtype(manifest["state_dtype"]), mode="r"
    )
    transitions = np.memmap(
        graph_dir / manifest["transitions_file"],
        dtype=np.dtype(manifest["transition_dtype"]),
        mode="r",
        shape=(manifest["state_count"], manifest["columns"]),
    )
    return manifest, states, transitions


def decode_state(value: int, history: int) -> tuple[int, int, int, int]:
    mask = (1 << history) - 1
    return tuple((value >> (part * history)) & mask for part in range(4))  # type: ignore[return-value]


def upward_weights(history: int, z: Fraction, scale: int = WEIGHT_SCALE):
    if not 0 < z < Fraction(1, 2):
        raise ValueError("z must lie in (0,1/2)")
    by_padding: dict[int, int] = {}
    exact: dict[int, Fraction] = {}
    errors: dict[int, Fraction] = {}
    for padding in range(-(history - 1), history):
        absolute = abs(padding)
        weight = z ** (history + 1) / (1 - z) if absolute == history - 1 else z ** (absolute + 2)
        numerator = (weight.numerator * scale + weight.denominator - 1) // weight.denominator
        by_padding[padding] = numerator
        exact[padding] = weight
        errors[padding] = Fraction(numerator, scale) - weight
    columns = np.array(
        [by_padding[padding] for _character in (0, 1) for padding in range(-(history - 1), history)],
        dtype=np.uint64,
    )
    return columns, exact, errors


@numba.njit(parallel=True, cache=True)
def apply_fixed(transitions, weights, witness, output):
    for state in numba.prange(transitions.shape[0]):
        total = np.uint64(0)
        for column in range(transitions.shape[1]):
            successor = transitions[state, column]
            if successor != REJECT:
                total += weights[column] * np.uint64(witness[successor])
        output[state] = total


@numba.njit(parallel=True, cache=True)
def normalize_fixed(raw, output, witness_scale, raw_max):
    factor = float(witness_scale) / float(raw_max)
    for state in numba.prange(raw.size):
        if raw[state] == raw_max:
            value = witness_scale
        else:
            value = int(float(raw[state]) * factor)
        if value < 1:
            value = 1
        elif value > witness_scale:
            value = witness_scale
        output[state] = np.uint32(value)


@numba.njit(cache=True)
def exact_ratio_scan(raw, witness):
    lambda_numerator = np.uint64(0)
    lambda_floor = np.uint64(0xFFFFFFFFFFFFFFFF)
    failing = np.int64(-1)
    for state in range(raw.size):
        value = np.uint64(witness[state])
        total = raw[state]
        ceiling = (total + value - np.uint64(1)) // value
        floor = total // value
        if ceiling > lambda_numerator:
            lambda_numerator = ceiling
        if floor < lambda_floor:
            lambda_floor = floor
    for state in range(raw.size):
        if raw[state] > lambda_numerator * np.uint64(witness[state]):
            failing = state
            break
    return lambda_numerator, lambda_floor, failing


def exact_target_check(
    z: Fraction, lambda_numerator: int, lambda_denominator: int, target_numerator: int, target_denominator: int
) -> bool:
    if not 0 < lambda_numerator < lambda_denominator:
        return False
    x = 2 * z
    lam = Fraction(lambda_numerator, lambda_denominator)
    for terms in (8, 16, 32, 64, 128, 256, 512):
        x_lower, x_upper = exact_log_interval(x, terms)
        lambda_lower, lambda_upper = exact_log_interval(lam, terms)
        # E >= 0 is exactly the desired power inequality.  Multipliers
        # are positive; subtraction reverses which lambda endpoint is safe.
        lower = 2 * target_denominator * x_lower - target_numerator * lambda_upper
        upper = 2 * target_denominator * x_upper - target_numerator * lambda_lower
        if lower >= 0:
            return True
        if upper < 0:
            return False
    raise ArithmeticError("exact logarithm intervals did not separate the target comparison")


def exact_log_interval(value: Fraction, terms: int) -> tuple[Fraction, Fraction]:
    """Return rigorous rational lower/upper bounds for ``log(value)``.

    The identity ``log(x)=2*sum(y^(2k+1)/(2k+1))`` with
    ``y=(x-1)/(x+1)`` has a geometrically bounded, same-sign tail.  No
    floating-point operation participates in these bounds.
    """

    if not isinstance(value, Fraction) or value <= 0:
        raise ValueError("exact_log_interval requires a positive Fraction")
    if terms <= 0:
        raise ValueError("terms must be positive")
    y = (value - 1) / (value + 1)
    y_squared = y * y
    power = y
    partial = Fraction(0)
    for index in range(terms):
        partial += power / (2 * index + 1)
        power *= y_squared
    partial *= 2
    remainder = 2 * abs(power) / ((2 * terms + 1) * (1 - y_squared))
    if y < 0:
        return partial - remainder, partial
    return partial, partial + remainder


def approximate_bound(z: Fraction, lambda_numerator: int, lambda_denominator: int) -> float:
    return 2.0 * math.log(2.0 * float(z)) / math.log(lambda_numerator / lambda_denominator)


def graph_identity(manifest: dict[str, Any]) -> str:
    payload = {
        "history": manifest["history"],
        "state_count": manifest["state_count"],
        "columns": manifest["columns"],
        "states_sha256": manifest["states_sha256"],
        "transitions_sha256": manifest["transitions_sha256"],
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def checkpoint_parameters(
    graph_manifest: dict[str, Any],
    z: Fraction,
    target_numerator: int,
    target_denominator: int,
    witness_scale: int = WITNESS_SCALE,
) -> dict[str, Any]:
    if not 1 <= witness_scale <= int(np.iinfo(np.uint32).max):
        raise ValueError("witness scale must fit positive uint32")
    return {
        "schema_version": 1,
        "kind": "lueker-upper-fixed-checkpoint",
        "kernel_version": KERNEL_VERSION,
        "history": graph_manifest["history"],
        "state_count": graph_manifest["state_count"],
        "columns": graph_manifest["columns"],
        "graph_identity": graph_identity(graph_manifest),
        "z_numerator": z.numerator,
        "z_denominator": z.denominator,
        "weight_scale": WEIGHT_SCALE,
        "witness_scale": witness_scale,
        "target_numerator": target_numerator,
        "target_denominator": target_denominator,
    }


def initialize_checkpoint(checkpoint_dir: Path, parameters: dict[str, Any]) -> dict[str, Any]:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    parameter_path = checkpoint_dir / "parameters.json"
    latest_path = checkpoint_dir / "latest.json"
    if parameter_path.exists() or latest_path.exists():
        raise FileExistsError("checkpoint already initialized")
    immutable = dict(parameters)
    immutable["created_at"] = utc_now()
    immutable["parameter_sha256"] = hashlib.sha256(canonical_json(parameters).encode()).hexdigest()
    atomic_json(parameter_path, immutable)
    witness = np.full(
        parameters["state_count"], parameters["witness_scale"], dtype=np.uint32
    )
    state_path = checkpoint_dir / "state-0.npy"
    state_sha = atomic_npy(state_path, witness)
    latest = {
        "schema_version": 1,
        "iteration": 0,
        "slot": 0,
        "state_file": state_path.name,
        "state_sha256": state_sha,
        "state_min": int(witness.min()),
        "state_max": int(witness.max()),
        "timestamp": utc_now(),
    }
    atomic_json(latest_path, latest)
    return latest


def load_checkpoint(
    checkpoint_dir: Path, expected_parameters: dict[str, Any], *, mmap_mode: str | None = None
):
    parameters = json.loads((checkpoint_dir / "parameters.json").read_text(encoding="utf-8"))
    comparable = {key: parameters[key] for key in expected_parameters}
    if comparable != expected_parameters:
        raise ValueError("checkpoint parameters do not match requested run")
    expected_parameter_sha = hashlib.sha256(canonical_json(expected_parameters).encode()).hexdigest()
    if parameters.get("parameter_sha256") != expected_parameter_sha:
        raise ValueError("checkpoint parameter SHA-256 mismatch")
    latest = json.loads((checkpoint_dir / "latest.json").read_text(encoding="utf-8"))
    state_path = checkpoint_dir / latest["state_file"]
    if sha256_file(state_path) != latest["state_sha256"]:
        raise ValueError("checkpoint state SHA-256 mismatch")
    witness = np.load(state_path, allow_pickle=False, mmap_mode=mmap_mode)
    if witness.dtype != np.uint32 or witness.shape != (expected_parameters["state_count"],):
        raise ValueError("checkpoint state shape/dtype mismatch")
    if int(witness.min()) <= 0 or int(witness.max()) > expected_parameters["witness_scale"]:
        raise ValueError("checkpoint witness outside positive fixed-point range")
    return parameters, latest, witness


def append_log_once(log_path: Path, record: dict[str, Any]) -> None:
    sweep_id = record["sweep_id"]
    if log_path.exists() and sweep_id in log_path.read_text(encoding="utf-8"):
        return
    line = f"- {record['timestamp']} upper-sweep `{canonical_json(record)}`\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def certify_witness(
    transitions,
    weights,
    witness,
    z: Fraction,
    target_numerator: int,
    target_denominator: int,
    raw_workspace=None,
):
    raw = np.empty(witness.size, dtype=np.uint64) if raw_workspace is None else raw_workspace
    started = time.perf_counter()
    apply_fixed(transitions, weights, witness, raw)
    apply_seconds = time.perf_counter() - started
    lambda_numerator, lambda_floor, failing = exact_ratio_scan(raw, witness)
    lambda_numerator = int(lambda_numerator)
    lambda_floor = int(lambda_floor)
    target_pass = exact_target_check(
        z, lambda_numerator, WEIGHT_SCALE, target_numerator, target_denominator
    )
    return {
        "lambda_numerator": lambda_numerator,
        "lambda_denominator": WEIGHT_SCALE,
        "lambda_floor": lambda_floor,
        "ratio_width_units": lambda_numerator - lambda_floor,
        "failing_state": int(failing),
        "feasible": int(failing) == -1,
        "target_pass": target_pass,
        "bound_approx": approximate_bound(z, lambda_numerator, WEIGHT_SCALE),
        "apply_seconds": apply_seconds,
        "raw_max": int(raw.max()),
    }


def run(
    graph_dir: Path,
    checkpoint_dir: Path,
    z: Fraction,
    max_iterations: int,
    tolerance_units: int,
    target_numerator: int,
    target_denominator: int,
    log_path: Path,
    threads: int,
    witness_scale: int = WITNESS_SCALE,
) -> dict[str, Any]:
    run_started = time.perf_counter()
    graph_manifest, _states, transitions = load_graph(graph_dir)
    parameters = checkpoint_parameters(
        graph_manifest, z, target_numerator, target_denominator, witness_scale
    )
    if not (checkpoint_dir / "latest.json").exists():
        initialize_checkpoint(checkpoint_dir, parameters)
    weights, _exact, _errors = upward_weights(graph_manifest["history"], z)
    if int(weights.sum()) * witness_scale >= 1 << 64:
        raise OverflowError("fixed-point row-sum preflight failed")
    numba.set_num_threads(threads)
    parameters_on_disk, latest, witness_on_disk = load_checkpoint(checkpoint_dir, parameters)
    witness = np.array(witness_on_disk, copy=True)
    del witness_on_disk
    raw = np.empty(witness.size, dtype=np.uint64)
    candidate = np.empty_like(witness)
    last_result: dict[str, Any] = {}
    for iteration in range(int(latest["iteration"]) + 1, max_iterations + 1):
        source_sha = latest["state_sha256"]
        optimize_started = time.perf_counter()
        apply_fixed(transitions, weights, witness, raw)
        raw_max = int(raw.max())
        normalize_fixed(raw, candidate, witness_scale, raw_max)
        optimize_seconds = time.perf_counter() - optimize_started
        certificate = certify_witness(
            transitions,
            weights,
            candidate,
            z,
            target_numerator,
            target_denominator,
            raw_workspace=raw,
        )
        slot = iteration & 1
        state_path = checkpoint_dir / f"state-{slot}.npy"
        checkpoint_started = time.perf_counter()
        state_sha = atomic_npy(state_path, candidate)
        checkpoint_seconds = time.perf_counter() - checkpoint_started
        timestamp = utc_now()
        record = {
            "kind": "upper-fixed-v1",
            "timestamp": timestamp,
            "iteration": iteration,
            "history": graph_manifest["history"],
            "states": graph_manifest["state_count"],
            "columns": graph_manifest["columns"],
            "z_numerator": z.numerator,
            "z_denominator": z.denominator,
            "weight_scale": WEIGHT_SCALE,
            "witness_scale": witness_scale,
            "lambda_numerator": certificate["lambda_numerator"],
            "lambda_denominator": WEIGHT_SCALE,
            "lambda_floor": certificate["lambda_floor"],
            "ratio_width_units": certificate["ratio_width_units"],
            "bound_approx": f"{certificate['bound_approx']:.12f}",
            "feasible": certificate["feasible"],
            "target_numerator": target_numerator,
            "target_denominator": target_denominator,
            "target_pass": certificate["target_pass"],
            "source_state_sha256": source_sha,
            "state_sha256": state_sha,
            "state_min": int(candidate.min()),
            "state_max": int(candidate.max()),
            "raw_max": certificate["raw_max"],
            "optimize_seconds": optimize_seconds,
            "certificate_seconds": certificate["apply_seconds"],
            "checkpoint_seconds": checkpoint_seconds,
            "run_elapsed_seconds": time.perf_counter() - run_started,
            "process_peak_rss_bytes": process_peak_rss_bytes(),
            "numba_threads": threads,
        }
        record["converged"] = bool(
            certificate["feasible"]
            and certificate["target_pass"]
            and certificate["ratio_width_units"] <= tolerance_units
        )
        record["sweep_id"] = hashlib.sha256(canonical_json(record).encode()).hexdigest()
        append_log_once(log_path, record)
        latest = {
            "schema_version": 1,
            "iteration": iteration,
            "slot": slot,
            "state_file": state_path.name,
            "state_sha256": state_sha,
            "state_min": record["state_min"],
            "state_max": record["state_max"],
            "timestamp": timestamp,
            "sweep_id": record["sweep_id"],
            "certificate": certificate,
        }
        atomic_json(checkpoint_dir / "latest.json", latest)
        print(canonical_json(record), flush=True)
        witness, candidate = candidate, witness
        last_result = record
        if record["converged"]:
            break
    return last_result


def certify_checkpoint(graph_dir: Path, checkpoint_dir: Path) -> dict[str, Any]:
    graph_manifest, _states, transitions = load_graph(graph_dir)
    parameter_file = json.loads((checkpoint_dir / "parameters.json").read_text(encoding="utf-8"))
    z = Fraction(parameter_file["z_numerator"], parameter_file["z_denominator"])
    expected = checkpoint_parameters(
        graph_manifest,
        z,
        parameter_file["target_numerator"],
        parameter_file["target_denominator"],
        parameter_file["witness_scale"],
    )
    _parameters, latest, witness = load_checkpoint(checkpoint_dir, expected, mmap_mode="r")
    weights, exact, errors = upward_weights(graph_manifest["history"], z)
    result = certify_witness(
        transitions,
        weights,
        witness,
        z,
        expected["target_numerator"],
        expected["target_denominator"],
    )
    result.update(
        {
            "status": "PASS" if result["feasible"] and result["target_pass"] else "FAIL",
            "iteration": latest["iteration"],
            "history": graph_manifest["history"],
            "state_count": graph_manifest["state_count"],
            "graph_identity": graph_identity(graph_manifest),
            "state_sha256": latest["state_sha256"],
            "z_numerator": z.numerator,
            "z_denominator": z.denominator,
            "target_numerator": expected["target_numerator"],
            "target_denominator": expected["target_denominator"],
            "witness_scale": expected["witness_scale"],
            "weight_rounding_direction": "upward",
            "weight_error_max_numerator": max(errors.values()).numerator,
            "weight_error_max_denominator": max(errors.values()).denominator,
            "weight_error_sum_numerator": sum(errors.values(), Fraction()).numerator * 2,
            "weight_error_sum_denominator": sum(errors.values(), Fraction()).denominator,
            "stored_state_error_units": 0,
            "integer_sum_error_units": 0,
            "feasibility_comparison_error_units": 0,
            "overflow_preflight": int(weights.sum()) * expected["witness_scale"] < 1 << 64,
            "maximum_full_row_sum": int(weights.sum()) * expected["witness_scale"],
            "uint64_max": (1 << 64) - 1,
            "machine": platform.platform(),
        }
    )
    return result


@numba.njit(parallel=True, cache=True)
def rescale_witness(source, output, factor):
    for index in numba.prange(source.size):
        output[index] = np.uint32(np.uint64(source[index]) * np.uint64(factor))


def rescale_checkpoint(
    graph_dir: Path,
    source_dir: Path,
    target_dir: Path,
    new_witness_scale: int,
) -> dict[str, Any]:
    """Create a restart-safe higher-precision checkpoint with the same witness."""

    graph_manifest = authenticate_graph(graph_dir)
    parameter_file = json.loads((source_dir / "parameters.json").read_text(encoding="utf-8"))
    old_scale = int(parameter_file["witness_scale"])
    if new_witness_scale <= old_scale or new_witness_scale % old_scale:
        raise ValueError("new witness scale must be an integer multiple of the old scale")
    factor = new_witness_scale // old_scale
    if new_witness_scale > int(np.iinfo(np.uint32).max):
        raise ValueError("new witness scale exceeds uint32")
    z = Fraction(parameter_file["z_numerator"], parameter_file["z_denominator"])
    old_expected = checkpoint_parameters(
        graph_manifest,
        z,
        parameter_file["target_numerator"],
        parameter_file["target_denominator"],
        old_scale,
    )
    _parameters, old_latest, source = load_checkpoint(
        source_dir, old_expected, mmap_mode="r"
    )
    new_expected = checkpoint_parameters(
        graph_manifest,
        z,
        parameter_file["target_numerator"],
        parameter_file["target_denominator"],
        new_witness_scale,
    )
    if target_dir.exists():
        raise FileExistsError("target checkpoint directory already exists")
    target_dir.mkdir(parents=True)
    immutable = dict(new_expected)
    immutable.update(
        {
            "created_at": utc_now(),
            "parameter_sha256": hashlib.sha256(
                canonical_json(new_expected).encode()
            ).hexdigest(),
            "parent_checkpoint": str(source_dir),
            "parent_iteration": int(old_latest["iteration"]),
            "parent_state_sha256": old_latest["state_sha256"],
            "rescale_factor": factor,
        }
    )
    atomic_json(target_dir / "parameters.json", immutable)
    output = np.empty(source.size, dtype=np.uint32)
    rescale_witness(source, output, factor)
    slot = int(old_latest["iteration"]) & 1
    state_path = target_dir / f"state-{slot}.npy"
    state_sha = atomic_npy(state_path, output)
    latest = {
        "schema_version": 1,
        "iteration": int(old_latest["iteration"]),
        "slot": slot,
        "state_file": state_path.name,
        "state_sha256": state_sha,
        "state_min": int(output.min()),
        "state_max": int(output.max()),
        "timestamp": utc_now(),
        "parent_state_sha256": old_latest["state_sha256"],
        "rescale_factor": factor,
        "certificate": old_latest.get("certificate"),
    }
    atomic_json(target_dir / "latest.json", latest)
    return {
        "status": "PASS",
        "source_checkpoint": str(source_dir),
        "target_checkpoint": str(target_dir),
        "iteration": latest["iteration"],
        "old_witness_scale": old_scale,
        "new_witness_scale": new_witness_scale,
        "factor": factor,
        "source_state_sha256": old_latest["state_sha256"],
        "state_sha256": state_sha,
        "state_min": latest["state_min"],
        "state_max": latest["state_max"],
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-graph")
    build.add_argument("--history", type=int, required=True)
    build.add_argument("--graph-dir", type=Path, required=True)
    build.add_argument("--force", action="store_true")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--graph-dir", type=Path, required=True)
    run_parser.add_argument("--checkpoint-dir", type=Path, required=True)
    run_parser.add_argument("--z-numerator", type=int, required=True)
    run_parser.add_argument("--z-denominator", type=int, required=True)
    run_parser.add_argument("--max-iterations", type=int, default=200)
    run_parser.add_argument("--tolerance-units", type=int, default=256)
    run_parser.add_argument("--target-numerator", type=int, default=826280)
    run_parser.add_argument("--target-denominator", type=int, default=1000000)
    run_parser.add_argument("--log", type=Path, default=Path("LOG.md"))
    run_parser.add_argument("--threads", type=int, default=18)
    run_parser.add_argument("--witness-scale", type=int, default=WITNESS_SCALE)
    certify = subparsers.add_parser("certify")
    certify.add_argument("--graph-dir", type=Path, required=True)
    certify.add_argument("--checkpoint-dir", type=Path, required=True)
    certify.add_argument("--output", type=Path)
    rescale = subparsers.add_parser("rescale-checkpoint")
    rescale.add_argument("--graph-dir", type=Path, required=True)
    rescale.add_argument("--source-dir", type=Path, required=True)
    rescale.add_argument("--target-dir", type=Path, required=True)
    rescale.add_argument("--new-witness-scale", type=int, required=True)
    return parser


def main() -> int:
    args = make_parser().parse_args()
    if args.command == "build-graph":
        result = build_graph(args.history, args.graph_dir, force=args.force)
    elif args.command == "run":
        result = run(
            args.graph_dir,
            args.checkpoint_dir,
            Fraction(args.z_numerator, args.z_denominator),
            args.max_iterations,
            args.tolerance_units,
            args.target_numerator,
            args.target_denominator,
            args.log,
            args.threads,
            args.witness_scale,
        )
    elif args.command == "certify":
        result = certify_checkpoint(args.graph_dir, args.checkpoint_dir)
        if args.output is not None:
            atomic_json(args.output, result)
    else:
        result = rescale_checkpoint(
            args.graph_dir,
            args.source_dir,
            args.target_dir,
            args.new_witness_scale,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status", "PASS") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
