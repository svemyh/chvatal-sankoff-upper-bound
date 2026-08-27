#!/usr/bin/env python3
"""Exact matrix-free verification of the published history-10 certificate."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parent
ARTIFACT_MANIFEST = ROOT / "matrix-free-h10-artifacts.json"
KERNEL_SOURCE = ROOT / "upper_matrix_free.c"
WEIGHT_SCALE = 1 << 32
UINT64_MAX = (1 << 64) - 1


class VerificationError(RuntimeError):
    """A fail-closed verification error."""


class KernelError(VerificationError):
    """The native verifier rejected an input or certificate row."""

    def __init__(self, message: str, result: dict[str, Any] | None = None):
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class Certificate:
    history: int
    state_count: int
    z: Fraction
    lambda_numerator: int
    lambda_denominator: int
    witness_scale: int
    target_numerator: int
    target_denominator: int

    @property
    def columns(self) -> int:
        return 2 * (2 * self.history - 1)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path, chunk_size: int = 8 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def load_artifact_manifest() -> dict[str, Any]:
    try:
        manifest = json.loads(ARTIFACT_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"cannot load artifact manifest: {error}") from error
    required = {"schema_version", "state_table", "witness", "certificate"}
    if manifest.get("schema_version") != 1 or not required.issubset(manifest):
        raise VerificationError("unsupported or incomplete artifact manifest")
    return manifest


def certificate_from_manifest(manifest: dict[str, Any]) -> Certificate:
    payload = manifest["certificate"]
    certificate = Certificate(
        history=int(payload["history"]),
        state_count=int(payload["state_count"]),
        z=Fraction(int(payload["z_numerator"]), int(payload["z_denominator"])),
        lambda_numerator=int(payload["lambda_numerator"]),
        lambda_denominator=int(payload["lambda_denominator"]),
        witness_scale=int(payload["witness_scale"]),
        target_numerator=int(payload["target_numerator"]),
        target_denominator=int(payload["target_denominator"]),
    )
    if certificate.lambda_denominator != WEIGHT_SCALE:
        raise VerificationError("certificate lambda denominator is not 2^32")
    if certificate.columns != int(payload["columns"]):
        raise VerificationError("certificate transition column count is inconsistent")
    if not 0 < certificate.z < Fraction(1, 2):
        raise VerificationError("certificate z is outside (0,1/2)")
    if not 0 < certificate.lambda_numerator < certificate.lambda_denominator:
        raise VerificationError("certificate lambda is outside (0,1)")
    return certificate


def authenticate_file(path: Path, expected_size: int, expected_sha256: str) -> str:
    try:
        actual_size = path.stat().st_size
    except FileNotFoundError as error:
        raise VerificationError(f"required artifact is absent: {path}") from error
    if actual_size != expected_size:
        raise VerificationError(
            f"artifact size mismatch for {path}: got {actual_size}, expected {expected_size}"
        )
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise VerificationError(
            f"artifact SHA-256 mismatch for {path}: got {actual_sha256}, "
            f"expected {expected_sha256}"
        )
    return actual_sha256


def _download(url: str, destination: Path) -> None:
    curl = shutil.which("curl")
    if curl is None:
        raise VerificationError("automatic artifact download requires curl")
    destination.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            curl,
            "--fail",
            "--location",
            "--retry",
            "5",
            "--retry-all-errors",
            "--continue-at",
            "-",
            "--output",
            str(destination),
            url,
        ],
        text=True,
    )
    if completed.returncode != 0:
        raise VerificationError(
            f"artifact download failed with exit {completed.returncode}: {url}"
        )


def _ensure_partial_download(
    destination: Path, *, url: str, size: int, sha256: str
) -> None:
    if destination.is_file():
        actual_size = destination.stat().st_size
        if actual_size == size:
            try:
                authenticate_file(destination, size, sha256)
                return
            except VerificationError:
                destination.unlink()
        elif actual_size > size:
            destination.unlink()
    _download(url, destination)
    authenticate_file(destination, size, sha256)


def ensure_downloaded_file(
    destination: Path, *, url: str, size: int, sha256: str
) -> Path:
    if destination.is_file():
        authenticate_file(destination, size, sha256)
        return destination
    partial = destination.with_name(f".{destination.name}.partial")
    _ensure_partial_download(partial, url=url, size=size, sha256=sha256)
    os.replace(partial, destination)
    return destination


def _sha256_file_segment(path: Path, offset: int, length: int) -> str:
    digest = hashlib.sha256()
    remaining = length
    with path.open("rb") as handle:
        handle.seek(offset)
        while remaining:
            block = handle.read(min(8 << 20, remaining))
            if not block:
                raise VerificationError(f"truncated assembled artifact: {path}")
            digest.update(block)
            remaining -= len(block)
    return digest.hexdigest()


def ensure_state_table(destination: Path, description: dict[str, Any]) -> Path:
    expected_size = int(description["bytes"])
    expected_sha = str(description["sha256"])
    if destination.is_file():
        authenticate_file(destination, expected_size, expected_sha)
        return destination
    parts = description.get("parts")
    if not isinstance(parts, list) or not parts:
        availability = description.get("availability", "UNKNOWN")
        raise VerificationError(
            "state-table artifact publication is deferred "
            f"(availability={availability}); pass --states PATH with the canonical "
            "authenticated table, or retry after the split-asset manifest is published"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    assembled = destination.with_name(f".{destination.name}.assembling")
    prefix_sizes = [0]
    for part in parts:
        prefix_sizes.append(prefix_sizes[-1] + int(part["bytes"]))
    current_size = assembled.stat().st_size if assembled.exists() else 0
    if current_size > expected_size:
        raise VerificationError(
            f"partial state-table is larger than the authenticated artifact: {assembled}"
        )
    completed_parts = 0
    for part_number, part in enumerate(parts):
        part_end = prefix_sizes[part_number + 1]
        if current_size < part_end:
            break
        actual_sha = _sha256_file_segment(
            assembled, prefix_sizes[part_number], int(part["bytes"])
        )
        if actual_sha != str(part["sha256"]):
            with assembled.open("r+b") as output:
                output.truncate(prefix_sizes[part_number])
            current_size = prefix_sizes[part_number]
            break
        completed_parts = part_number + 1
    completed_size = prefix_sizes[completed_parts]
    if current_size != completed_size:
        with assembled.open("r+b") as output:
            output.truncate(completed_size)
        current_size = completed_size
    next_part = completed_parts
    for part_number in range(next_part, len(parts)):
        part = parts[part_number]
        part_path = destination.parent / f".{part['name']}.partial"
        _ensure_partial_download(
            part_path,
            url=str(part["url"]),
            size=int(part["bytes"]),
            sha256=str(part["sha256"]),
        )
        with assembled.open("ab") as output, part_path.open("rb") as source:
            while block := source.read(8 << 20):
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        part_path.unlink()
    authenticate_file(assembled, expected_size, expected_sha)
    os.replace(assembled, destination)
    return destination


def prepare_record_artifacts(
    work_dir: Path,
    manifest: dict[str, Any],
    *,
    states_override: Path | None = None,
    witness_override: Path | None = None,
) -> tuple[Path, Path]:
    artifacts = work_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    state_description = manifest["state_table"]
    witness_description = manifest["witness"]
    states = (
        states_override.resolve()
        if states_override is not None
        else ensure_state_table(artifacts / state_description["name"], state_description)
    )
    witness = (
        witness_override.resolve()
        if witness_override is not None
        else ensure_downloaded_file(
            artifacts / witness_description["name"],
            url=str(witness_description["url"]),
            size=int(witness_description["bytes"]),
            sha256=str(witness_description["sha256"]),
        )
    )
    authenticate_file(
        states, int(state_description["bytes"]), str(state_description["sha256"])
    )
    authenticate_file(
        witness, int(witness_description["bytes"]), str(witness_description["sha256"])
    )
    return states, witness


def upward_weights(certificate: Certificate) -> list[int]:
    result: list[int] = []
    for _character in (0, 1):
        for padding in range(-(certificate.history - 1), certificate.history):
            absolute = abs(padding)
            exact = (
                certificate.z ** (certificate.history + 1) / (1 - certificate.z)
                if absolute == certificate.history - 1
                else certificate.z ** (absolute + 2)
            )
            integer = (
                exact.numerator * WEIGHT_SCALE + exact.denominator - 1
            ) // exact.denominator
            result.append(integer)
    if len(result) != certificate.columns:
        raise VerificationError("fixed-point weight count is inconsistent")
    worst_row = sum(result) * certificate.witness_scale
    if worst_row > UINT64_MAX:
        raise VerificationError("fixed-point row-sum uint64 preflight failed")
    return result


def index_capacity(state_count: int) -> int:
    if not 0 < state_count < (1 << 32) - 1:
        raise VerificationError("state count is outside the uint32 index domain")
    required = (state_count * 100 + 79) // 80
    return 1 << (required - 1).bit_length()


def compiler_command() -> list[str]:
    command = shlex.split(os.environ.get("CC", "cc"))
    if not command:
        raise VerificationError("CC must identify a C compiler")
    return command


def compile_kernel(work_dir: Path) -> tuple[Path, dict[str, str]]:
    source_sha = sha256_file(KERNEL_SOURCE)
    runtime_root = work_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    runtime_dir = Path(
        tempfile.mkdtemp(prefix=f"upper-matrix-free-{source_sha[:16]}-", dir=runtime_root)
    )
    os.chmod(runtime_dir, 0o700)
    binary = runtime_dir / "upper_matrix_free"
    command = compiler_command()
    try:
        completed = subprocess.run(
            command
            + [
                "-O3",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pthread",
                str(KERNEL_SOURCE),
                "-o",
                str(binary),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode != 0:
            raise VerificationError(
                f"matrix-free C verifier compilation failed:\n{completed.stderr}"
            )
        os.chmod(binary, 0o500)
    except BaseException:
        shutil.rmtree(runtime_dir, ignore_errors=True)
        raise
    version = subprocess.run(
        command + ["--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    ).stdout.splitlines()[0]
    return binary, {
        "status": "COMPILED_FRESH",
        "private_runtime_directory": True,
        "source_sha256": source_sha,
        "binary_sha256": sha256_file(binary),
        "compiler": version,
        "compiler_command": " ".join(command),
    }


def _parse_kernel_result(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    result: dict[str, Any] | None = None
    if lines:
        try:
            parsed = json.loads(lines[-1])
            if isinstance(parsed, dict):
                result = parsed
        except json.JSONDecodeError:
            result = None
    if completed.returncode != 0 or result is None or result.get("status") != "PASS":
        detail = result if result is not None else completed.stderr.strip()
        raise KernelError(f"matrix-free kernel rejected the run: {detail}", result)
    return result


def run_kernel(
    command: Sequence[str], *, executable_sha256: str
) -> dict[str, Any]:
    if not command:
        raise VerificationError("native verifier command is empty")
    executable = Path(command[0])
    if not executable.is_file():
        raise VerificationError(f"native verifier is absent: {executable}")
    actual_sha256 = sha256_file(executable)
    if actual_sha256 != executable_sha256:
        raise VerificationError(
            "native verifier changed after its fresh compilation: "
            f"got {actual_sha256}, expected {executable_sha256}"
        )
    try:
        completed = subprocess.run(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise VerificationError(
            f"cannot execute native verifier {executable}: {error}"
        ) from error
    return _parse_kernel_result(completed)


def build_fresh_index(
    kernel: Path,
    work_dir: Path,
    states: Path,
    *,
    history: int,
    state_count: int,
    state_sha256: str,
    kernel_source_sha256: str,
    kernel_binary_sha256: str,
) -> tuple[Path, int, dict[str, Any]]:
    capacity = index_capacity(state_count)
    cache = work_dir / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    index = cache / f"states-{state_sha256[:16]}-{capacity}.index.u32"
    metadata_path = index.with_suffix(".json")
    expected_metadata = {
        "schema_version": 1,
        "kind": "matrix-free-keyless-state-index",
        "history": history,
        "state_count": state_count,
        "state_sha256": state_sha256,
        "capacity": capacity,
        "bytes": capacity * 4,
        "kernel_source_sha256": kernel_source_sha256,
        "kernel_binary_sha256": kernel_binary_sha256,
    }
    index.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
    partial = index.with_name(f".{index.name}.partial")
    partial.unlink(missing_ok=True)
    started = time.perf_counter()
    result = run_kernel(
        [
            str(kernel),
            "index",
            str(history),
            str(states),
            str(state_count),
            str(partial),
            str(capacity),
        ],
        executable_sha256=kernel_binary_sha256,
    )
    if partial.stat().st_size != expected_metadata["bytes"]:
        raise VerificationError("fresh membership index has the wrong size")
    os.replace(partial, index)
    atomic_json(metadata_path, expected_metadata)
    return index, capacity, {
        **result,
        "status": "BUILT_FRESH",
        "build_seconds": time.perf_counter() - started,
        **expected_metadata,
    }


def load_witness(path: Path, state_count: int) -> np.memmap:
    try:
        witness = np.load(path, allow_pickle=False, mmap_mode="r")
    except (OSError, ValueError) as error:
        raise VerificationError(f"cannot parse witness .npy artifact: {error}") from error
    if not isinstance(witness, np.memmap):
        raise VerificationError("witness did not load as a memory map")
    if witness.dtype.str != "<u4":
        raise VerificationError(
            f"witness dtype mismatch: got {witness.dtype.str}, expected <u4"
        )
    if witness.shape != (state_count,):
        raise VerificationError(
            f"witness shape mismatch: got {witness.shape}, expected {(state_count,)}"
        )
    if witness.offset % 4:
        raise VerificationError("witness data offset is not uint32 aligned")
    if path.stat().st_size != witness.offset + state_count * 4:
        raise VerificationError("witness contains trailing or truncated bytes")
    return witness


def scan_chunk(
    kernel: Path,
    *,
    certificate: Certificate,
    states: Path,
    index: Path,
    capacity: int,
    witness: Path,
    witness_offset: int,
    weights: Sequence[int],
    start: int,
    end: int,
    threads: int,
    kernel_binary_sha256: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = run_kernel(
        [
            str(kernel),
            "scan",
            str(certificate.history),
            str(states),
            str(certificate.state_count),
            str(index),
            str(capacity),
            str(witness),
            str(witness_offset),
            str(start),
            str(end),
            str(threads),
            str(certificate.lambda_numerator),
            str(certificate.witness_scale),
            *(str(weight) for weight in weights),
        ],
        executable_sha256=kernel_binary_sha256,
    )
    result["scan_seconds"] = time.perf_counter() - started
    return result


def _checkpoint_chain(previous: str, chunk: dict[str, Any]) -> str:
    return sha256_bytes((previous + canonical_json(chunk)).encode())


def _validate_fresh_chunk_result(
    result: dict[str, Any], *, start: int, end: int, columns: int
) -> None:
    expected_rows = end - start
    try:
        reported_start = int(result.get("start_row", -1))
        reported_end = int(result.get("end_row", -1))
        reported_rows = int(result.get("rows", -1))
        accepted = int(result.get("accepted_transitions", -1))
        rejected = int(result.get("rejected_transitions", -1))
    except (TypeError, ValueError) as error:
        raise VerificationError("native verifier reported malformed counts") from error
    if reported_start != start or reported_end != end or reported_rows != expected_rows:
        raise VerificationError("native verifier reported the wrong row range")
    if accepted < 0 or rejected < 0 or accepted + rejected != expected_rows * columns:
        raise VerificationError("native verifier reported the wrong transition count")


def aggregate_chunks(chunks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not chunks:
        return {
            "rows": 0,
            "accepted_transitions": 0,
            "rejected_transitions": 0,
            "maximum_ceiling": 0,
            "minimum_floor": UINT64_MAX,
            "raw_maximum": 0,
            "witness_minimum": UINT64_MAX,
            "witness_maximum": 0,
            "peak_rss_bytes": 0,
            "scan_seconds": 0.0,
        }
    return {
        "rows": sum(int(chunk["rows"]) for chunk in chunks),
        "accepted_transitions": sum(
            int(chunk["accepted_transitions"]) for chunk in chunks
        ),
        "rejected_transitions": sum(
            int(chunk["rejected_transitions"]) for chunk in chunks
        ),
        "maximum_ceiling": max(int(chunk["maximum_ceiling"]) for chunk in chunks),
        "minimum_floor": min(int(chunk["minimum_floor"]) for chunk in chunks),
        "raw_maximum": max(int(chunk["raw_maximum"]) for chunk in chunks),
        "witness_minimum": min(int(chunk["witness_minimum"]) for chunk in chunks),
        "witness_maximum": max(int(chunk["witness_maximum"]) for chunk in chunks),
        "peak_rss_bytes": max(int(chunk["peak_rss_bytes"]) for chunk in chunks),
        "scan_seconds": sum(float(chunk["scan_seconds"]) for chunk in chunks),
    }


def scan_certified_fresh(
    kernel: Path,
    *,
    certificate: Certificate,
    states: Path,
    state_sha256: str,
    index: Path,
    capacity: int,
    witness: Path,
    witness_sha256: str,
    witness_offset: int,
    weights: Sequence[int],
    progress_path: Path,
    kernel_source_sha256: str,
    kernel_binary_sha256: str,
    chunk_rows: int,
    threads: int,
    stop_after_chunks: int | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if chunk_rows < 1 or threads < 1:
        raise VerificationError("chunk rows and threads must be positive")
    invocation = {
        "invocation_nonce": os.urandom(32).hex(),
        "certification_mode": "all_rows_fresh_current_invocation",
        "history": certificate.history,
        "state_count": certificate.state_count,
        "columns": certificate.columns,
        "state_sha256": state_sha256,
        "witness_sha256": witness_sha256,
        "witness_offset": witness_offset,
        "index_capacity": capacity,
        "weights": list(weights),
        "lambda_numerator": certificate.lambda_numerator,
        "lambda_denominator": certificate.lambda_denominator,
        "witness_scale": certificate.witness_scale,
        "chunk_rows": chunk_rows,
        "kernel_source_sha256": kernel_source_sha256,
        "kernel_binary_sha256": kernel_binary_sha256,
    }
    chain = sha256_bytes(canonical_json(invocation).encode())
    chunks: list[dict[str, Any]] = []
    progress = {
        "schema_version": 2,
        "kind": "matrix-free-current-invocation-progress",
        "certifying_resume_supported": False,
        "proof_credit": "current_process_memory_only",
        "invocation": invocation,
        "chunks": chunks,
        "chain_sha256": chain,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    # A progress file is a user-facing continuity aid only.  Overwrite it and
    # retain proof-bearing summaries in this process so no writable cache can
    # contribute work to a certified result.
    atomic_json(progress_path, progress)

    invocation_chunks = 0
    next_row = 0
    while next_row < certificate.state_count:
        end_row = min(next_row + chunk_rows, certificate.state_count)
        result = scan_chunk(
            kernel,
            certificate=certificate,
            states=states,
            index=index,
            capacity=capacity,
            witness=witness,
            witness_offset=witness_offset,
            weights=weights,
            start=next_row,
            end=end_row,
            threads=threads,
            kernel_binary_sha256=kernel_binary_sha256,
        )
        _validate_fresh_chunk_result(
            result, start=next_row, end=end_row, columns=certificate.columns
        )
        content = dict(result)
        content.pop("status", None)
        chain = _checkpoint_chain(chain, content)
        content["chain_sha256"] = chain
        chunks.append(content)
        progress["chunks"] = chunks
        progress["chain_sha256"] = chain
        progress["updated_at"] = utc_now()
        atomic_json(progress_path, progress)
        next_row = end_row
        invocation_chunks += 1
        print(
            f"[matrix-free] rows {next_row:,}/{certificate.state_count:,} "
            f"({100 * next_row / certificate.state_count:.2f}%)",
            flush=True,
        )
        if (
            stop_after_chunks is not None
            and invocation_chunks >= stop_after_chunks
            and next_row < certificate.state_count
        ):
            return (
                "INCOMPLETE",
                aggregate_chunks(chunks),
                {
                    "fresh_start_row": 0,
                    "next_row": next_row,
                    "fresh_chunks": len(chunks),
                    "cross_invocation_resume": False,
                    "invocation_scan_chain_sha256": chain,
                },
            )
    return (
        "PASS",
        aggregate_chunks(chunks),
        {
            "fresh_start_row": 0,
            "next_row": next_row,
            "fresh_chunks": len(chunks),
            "cross_invocation_resume": False,
            "invocation_scan_chain_sha256": chain,
        },
    )


def exact_power_decision(
    z: Fraction,
    lambda_numerator: int,
    lambda_denominator: int,
    target_numerator: int,
    target_denominator: int,
) -> bool:
    if not 0 < 2 * z < 1:
        raise VerificationError("exact bound conversion requires 0 < 2z < 1")
    if not 0 < lambda_numerator < lambda_denominator:
        raise VerificationError("exact bound conversion requires 0 < lambda < 1")
    exponent = 2 * target_denominator
    left = pow(2 * z.numerator, exponent) * pow(
        lambda_denominator, target_numerator
    )
    right = pow(z.denominator, exponent) * pow(
        lambda_numerator, target_numerator
    )
    return left >= right


def exact_bound_evidence(certificate: Certificate) -> dict[str, Any]:
    passed = exact_power_decision(
        certificate.z,
        certificate.lambda_numerator,
        certificate.lambda_denominator,
        certificate.target_numerator,
        certificate.target_denominator,
    )
    if not passed:
        raise VerificationError("the exact rational bound conversion failed")
    return {
        "method": "direct_integer_power_comparison",
        "identity": (
            "(2z)^(2*target_denominator) >= "
            "lambda^(target_numerator)"
        ),
        "z": f"{certificate.z.numerator}/{certificate.z.denominator}",
        "lambda": (
            f"{certificate.lambda_numerator}/{certificate.lambda_denominator}"
        ),
        "target": (
            f"{certificate.target_numerator}/{certificate.target_denominator}"
        ),
        "result": True,
    }


def artifact_snapshot(paths: Sequence[Path]) -> dict[str, tuple[int, int, int]]:
    return {
        str(path): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            path.stat().st_ino,
        )
        for path in paths
    }


def source_hashes() -> dict[str, str]:
    paths = [
        Path(__file__).resolve(),
        KERNEL_SOURCE,
        ARTIFACT_MANIFEST,
        ROOT / "uv.lock",
    ]
    return {path.name: sha256_file(path) for path in paths}


def validate_record_result(
    aggregate: dict[str, Any],
    certificate: Certificate,
    expected: dict[str, Any],
) -> None:
    if aggregate["rows"] != certificate.state_count:
        raise VerificationError("not every supplied state row was verified")
    transitions = aggregate["accepted_transitions"] + aggregate["rejected_transitions"]
    if transitions != certificate.state_count * certificate.columns:
        raise VerificationError("not every mathematical transition was regenerated")
    checks = {
        "maximum_ceiling": int(expected["maximum_ceiling"]),
        "minimum_floor": int(expected["minimum_floor"]),
        "raw_maximum": int(expected["raw_maximum"]),
        "witness_minimum": int(expected["witness_minimum"]),
        "witness_maximum": int(expected["witness_maximum"]),
    }
    for key, value in checks.items():
        if int(aggregate[key]) != value:
            raise VerificationError(
                f"record diagnostic mismatch for {key}: got {aggregate[key]}, "
                f"expected {value}"
            )


def preflight(
    work_dir: Path,
    manifest: dict[str, Any],
    *,
    needs_state_download: bool,
) -> dict[str, Any]:
    state_bytes = int(manifest["state_table"]["bytes"])
    witness_bytes = int(manifest["witness"]["bytes"])
    state_count = int(manifest["certificate"]["state_count"])
    derived_index_bytes = index_capacity(state_count) * 4
    parts = manifest["state_table"].get("parts", [])
    if needs_state_download and not parts:
        raise VerificationError(
            "automatic state-table download is unavailable because publication is deferred; "
            "pass --states PATH with the canonical authenticated table"
        )
    largest_part = max((int(part["bytes"]) for part in parts), default=0)
    required_free = state_bytes + witness_bytes + derived_index_bytes + largest_part + (1 << 30)
    disk = shutil.disk_usage(work_dir)
    if disk.free < required_free:
        raise VerificationError(
            f"insufficient free disk: need {required_free} bytes, have {disk.free}"
        )
    return {
        "required_free_bytes": required_free,
        "available_free_bytes": disk.free,
        "state_table_bytes": state_bytes,
        "witness_bytes": witness_bytes,
        "derived_index_bytes": derived_index_bytes,
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "matrix-free-h10-verification",
        help="download, fresh derived-index, progress, and evidence directory",
    )
    parser.add_argument("--states", type=Path, help="authenticated local state-table override")
    parser.add_argument("--witness", type=Path, help="authenticated local witness override")
    parser.add_argument("--threads", type=int, default=min(18, os.cpu_count() or 1))
    parser.add_argument("--chunk-rows", type=int, default=10_000_000)
    parser.add_argument(
        "--stop-after-chunks",
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        help="evidence JSON path (default: WORK_DIR/verification-evidence.json)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    invocation_started = time.perf_counter()
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = (
        args.evidence.resolve()
        if args.evidence is not None
        else work_dir / "verification-evidence.json"
    )
    atomic_json(
        evidence_path,
        {
            "schema_version": 1,
            "status": "IN_PROGRESS",
            "started_at": utc_now(),
        },
    )

    manifest = load_artifact_manifest()
    certificate = certificate_from_manifest(manifest)
    disk = preflight(
        work_dir, manifest, needs_state_download=args.states is None
    )
    states, witness_path = prepare_record_artifacts(
        work_dir,
        manifest,
        states_override=args.states,
        witness_override=args.witness,
    )
    artifact_before = artifact_snapshot([states, witness_path])
    state_sha = str(manifest["state_table"]["sha256"])
    witness_sha = str(manifest["witness"]["sha256"])
    witness = load_witness(witness_path, certificate.state_count)
    witness_offset = int(witness.offset)
    del witness

    kernel, kernel_details = compile_kernel(work_dir)
    state_index, capacity, index_details = build_fresh_index(
        kernel,
        work_dir,
        states,
        history=certificate.history,
        state_count=certificate.state_count,
        state_sha256=state_sha,
        kernel_source_sha256=kernel_details["source_sha256"],
        kernel_binary_sha256=kernel_details["binary_sha256"],
    )
    weights = upward_weights(certificate)
    status, aggregate, fresh_scan = scan_certified_fresh(
        kernel,
        certificate=certificate,
        states=states,
        state_sha256=state_sha,
        index=state_index,
        capacity=capacity,
        witness=witness_path,
        witness_sha256=witness_sha,
        witness_offset=witness_offset,
        weights=weights,
        progress_path=work_dir / "verification-progress.json",
        kernel_source_sha256=kernel_details["source_sha256"],
        kernel_binary_sha256=kernel_details["binary_sha256"],
        chunk_rows=args.chunk_rows,
        threads=args.threads,
        stop_after_chunks=args.stop_after_chunks,
    )
    if status == "INCOMPLETE":
        atomic_json(
            evidence_path,
            {
                "schema_version": 1,
                "status": "INCOMPLETE_NON_CERTIFYING",
                "fresh_rows_scanned": aggregate["rows"],
                "state_count": certificate.state_count,
                "certifying_resume_supported": False,
                "progress": str(work_dir / "verification-progress.json"),
            },
        )
        print(
            json.dumps(
                {
                    "status": "INCOMPLETE_NON_CERTIFYING",
                    "fresh_rows_scanned": aggregate["rows"],
                    "state_count": certificate.state_count,
                    "certifying_resume_supported": False,
                },
                sort_keys=True,
            )
        )
        return 3

    validate_record_result(aggregate, certificate, manifest["expected_result"])
    bound = exact_bound_evidence(certificate)
    if artifact_snapshot([states, witness_path]) != artifact_before:
        raise VerificationError("a proof artifact changed during verification")
    authenticate_file(
        states,
        int(manifest["state_table"]["bytes"]),
        str(manifest["state_table"]["sha256"]),
    )
    authenticate_file(
        witness_path,
        int(manifest["witness"]["bytes"]),
        str(manifest["witness"]["sha256"]),
    )
    code_hashes = source_hashes()
    evidence = {
        "schema_version": 1,
        "kind": "chvatal-sankoff-matrix-free-verification-evidence",
        "status": "PASS",
        "completed_at": utc_now(),
        "theorem": "gamma_2 <= 824443/1000000",
        "parameters": {
            "history": certificate.history,
            "state_count": certificate.state_count,
            "columns": certificate.columns,
            "z_numerator": certificate.z.numerator,
            "z_denominator": certificate.z.denominator,
            "lambda_numerator": certificate.lambda_numerator,
            "lambda_denominator": certificate.lambda_denominator,
            "witness_scale": certificate.witness_scale,
            "target_numerator": certificate.target_numerator,
            "target_denominator": certificate.target_denominator,
            "weights": weights,
        },
        "artifact_hashes": {
            "states_sha256": state_sha,
            "witness_sha256": witness_sha,
        },
        "code_hashes": {
            **code_hashes,
            "kernel_binary": kernel_details["binary_sha256"],
        },
        "counts": {
            "rows": aggregate["rows"],
            "accepted_transitions": aggregate["accepted_transitions"],
            "rejected_transitions": aggregate["rejected_transitions"],
        },
        "exact_result": {
            "all_rows_feasible": True,
            "maximum_ceiling": aggregate["maximum_ceiling"],
            "minimum_floor": aggregate["minimum_floor"],
            "raw_maximum": aggregate["raw_maximum"],
            "witness_minimum": aggregate["witness_minimum"],
            "witness_maximum": aggregate["witness_maximum"],
            "peak_scan_rss_bytes": aggregate["peak_rss_bytes"],
            "bound_conversion": bound,
        },
        "runtime": {
            "scan_seconds": aggregate["scan_seconds"],
            "invocation_wall_seconds": time.perf_counter() - invocation_started,
            **fresh_scan,
        },
        "certification": {
            "all_rows_scanned_current_invocation": True,
            "cross_invocation_resume_used": False,
            "cached_chunk_summaries_trusted": False,
            "kernel_compiled_current_invocation": True,
            "state_index_built_current_invocation": True,
        },
        "platform": {
            "platform": platform.platform(),
            "python": sys.version,
            "threads": args.threads,
            **kernel_details,
        },
        "storage": disk,
        "derived_index": index_details,
        "invocation_scan_chain_sha256": fresh_scan[
            "invocation_scan_chain_sha256"
        ],
        "transition_graph_used": False,
    }
    atomic_json(evidence_path, evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    print(
        "PASS: exact matrix-free verification proves gamma_2 <= 0.824443",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as error:
        print(f"FAIL: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
