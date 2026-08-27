#!/usr/bin/env python3
"""Read-only exact replay of the binary Chvatal--Sankoff upper certificate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from fractions import Fraction


ROOT = Path(__file__).resolve().parent

# This verifier uses NumPy and Numba for the 400-million-state scan.  Every
# inequality that decides the claim is evaluated in Python integers and
# fractions (see exact_log_interval / exact_target_decision); NumPy is used
# only to apply the operator and compare integers at scale.
sys.dont_write_bytecode = True
try:
    import numba
    import numpy as np
except ModuleNotFoundError as error:  # pragma: no cover - environment guard
    raise SystemExit(
        "verify_upper.py needs the locked dependencies: run uv sync --frozen"
    ) from error


WEIGHT_SCALE = 1 << 32
REJECT = np.uint32(0xFFFFFFFF)
UINT64_MAX = (1 << 64) - 1
PAPER_SHA256 = "d812c50d68c1b7e6f7e63eb5537cc470aaad37e1cc93aa3c1d969dfc53398778"
CERTIFICATE_SHA256 = "523fb826c7c7e18310cb1625a04d375017ed228bef911063634022560ff012ff"

EXPECTED = {
    "calibration": {
        "history": 8,
        "state_count": 6_419_109,
        "columns": 30,
        "graph_identity": "4c2514a4066e745d3da90a074cd1dbc5978eecd3259d795c00fd2f9313b8d084",
        "states_sha256": "c1288560c59890d29e181d445fb419ac639378001c9182ea7d5a21706320936f",
        "transitions_sha256": "95d566129119c52aa003c1df4601cbfe172032854c942b8572e1e16df5d8bc87",
        "state_sha256": "48c9b399a30f0bae01999d435af73f9a799a7e2a5c6d83aca69a280419dd2714",
        "iteration": 203,
        "witness_scale": 1 << 26,
        "lambda_numerator": 1_468_159_907,
        "lambda_floor": 1_468_157_974,
        "ratio_width_units": 1_933,
        "state_min": 992_299,
        "state_max": 67_108_864,
    },
    "record": {
        "history": 10,
        "state_count": 400_253_317,
        "columns": 38,
        "graph_identity": "e4db7c10b0b55060c3a9beff010583a593b4c24bc13600ecb219b933a2806f7a",
        "states_sha256": "defc127da935708620977efddda218378322d9d23921ac3453c9f7a56ff5f59b",
        "transitions_sha256": "611a32eb44baa93fbe5231aa8ddaf9aa690da4e4b2a049ff54226ce3e265aba5",
        "state_sha256": "e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436",
        "iteration": 113,
        "witness_scale": 1 << 31,
        "lambda_numerator": 1_464_651_560,
        "lambda_floor": 1_464_649_541,
        "ratio_width_units": 2_019,
        "state_min": 9_834_007,
        "state_max": 2_147_483_648,
    },
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256_file(path: Path, chunk_size: int = 8 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def graph_identity(manifest: dict) -> str:
    payload = {
        "history": manifest["history"],
        "state_count": manifest["state_count"],
        "columns": manifest["columns"],
        "states_sha256": manifest["states_sha256"],
        "transitions_sha256": manifest["transitions_sha256"],
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def snapshot(paths: list[Path]) -> dict[str, tuple[int, int, int]]:
    result = {}
    for path in paths:
        stat = path.stat()
        result[str(path)] = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
    return result


def upward_weights(history: int, z: Fraction) -> tuple[np.ndarray, dict]:
    integers = []
    errors = []
    for _character in (0, 1):
        for padding in range(-(history - 1), history):
            absolute = abs(padding)
            exact = (
                z ** (history + 1) / (1 - z)
                if absolute == history - 1
                else z ** (absolute + 2)
            )
            integer = (exact.numerator * WEIGHT_SCALE + exact.denominator - 1) // exact.denominator
            integers.append(integer)
            errors.append(Fraction(integer, WEIGHT_SCALE) - exact)
    return np.asarray(integers, dtype=np.uint64), {
        "maximum": max(errors),
        "sum": sum(errors, Fraction()),
    }


@numba.njit(parallel=True)
def apply_integer_operator(transitions, weights, witness, output):
    for state in numba.prange(transitions.shape[0]):
        total = np.uint64(0)
        for column in range(transitions.shape[1]):
            successor = transitions[state, column]
            if successor != REJECT:
                # Bounds checks are normally disabled inside Numba kernels.
                # Use an impossible row-sum sentinel instead of indexing an
                # out-of-range successor, then reject it explicitly below.
                if successor >= witness.size:
                    total = np.uint64(UINT64_MAX)
                    break
                total += weights[column] * np.uint64(witness[successor])
        output[state] = total


@numba.njit
def first_invalid_successor_row(raw):
    for state in range(raw.size):
        if raw[state] == np.uint64(UINT64_MAX):
            return state
    return -1


@numba.njit
def scan_integer_ratios(raw, witness, pinned_lambda):
    """Return (max ceil ratio, min floor ratio, first state violating pinned_lambda).

    The third value is a genuine per-state test of the certificate inequality
    S_i <= Lambda * V_i against the Lambda pinned in EXPECTED, i.e. a constant
    fixed independently of this data.  (An earlier revision compared against
    the maximum computed from the same scan, which is vacuous by construction.)
    """
    maximum_ceiling = np.uint64(0)
    minimum_floor = np.uint64(UINT64_MAX)
    for state in range(raw.size):
        value = np.uint64(witness[state])
        total = raw[state]
        ceiling = (total + value - np.uint64(1)) // value
        floor = total // value
        if ceiling > maximum_ceiling:
            maximum_ceiling = ceiling
        if floor < minimum_floor:
            minimum_floor = floor
    failing = np.int64(-1)
    for state in range(raw.size):
        if raw[state] > pinned_lambda * np.uint64(witness[state]):
            failing = state
            break
    return maximum_ceiling, minimum_floor, failing


def exact_log_interval(value: Fraction, terms: int) -> tuple[Fraction, Fraction]:
    require(value > 0, "log input must be positive")
    y = (value - 1) / (value + 1)
    y_squared = y * y
    power = y
    partial = Fraction()
    for index in range(terms):
        partial += power / (2 * index + 1)
        power *= y_squared
    partial *= 2
    remainder = 2 * abs(power) / ((2 * terms + 1) * (1 - y_squared))
    return (partial - remainder, partial) if y < 0 else (partial, partial + remainder)


def exact_target_decision(
    z: Fraction,
    lambda_numerator: int,
    target_numerator: int,
    target_denominator: int,
) -> tuple[bool, int]:
    lam = Fraction(lambda_numerator, WEIGHT_SCALE)
    require(0 < 2 * z < 1 and 0 < lam < 1, "normalization domain failure")
    for terms in (8, 16, 32, 64, 128, 256, 512):
        x_lower, x_upper = exact_log_interval(2 * z, terms)
        lambda_lower, lambda_upper = exact_log_interval(lam, terms)
        lower = 2 * target_denominator * x_lower - target_numerator * lambda_upper
        upper = 2 * target_denominator * x_upper - target_numerator * lambda_lower
        if lower >= 0:
            return True, terms
        if upper < 0:
            return False, terms
    raise VerificationError("exact log intervals did not separate target")


def authenticate_graph(graph_dir: Path, expected: dict) -> tuple[dict, np.memmap]:
    manifest = json.loads((graph_dir / "graph.json").read_text())
    require(manifest["kind"] == "lueker-upper-dense-graph", "unexpected graph kind")
    for key in ("history", "state_count", "columns"):
        require(manifest[key] == expected[key], f"graph {key} mismatch")
    for prefix in ("states", "transitions"):
        path = graph_dir / manifest[f"{prefix}_file"]
        require(path.stat().st_size == manifest[f"{prefix}_bytes"], f"{prefix} size mismatch")
        digest = sha256_file(path)
        require(digest == manifest[f"{prefix}_sha256"], f"{prefix} manifest hash mismatch")
        require(digest == expected[f"{prefix}_sha256"], f"{prefix} expected hash mismatch")
    require(graph_identity(manifest) == expected["graph_identity"], "graph identity mismatch")
    transitions = np.memmap(
        graph_dir / manifest["transitions_file"],
        dtype=np.dtype(manifest["transition_dtype"]),
        mode="r",
        shape=(manifest["state_count"], manifest["columns"]),
    )
    return manifest, transitions


def authenticate_checkpoint(
    checkpoint_dir: Path,
    expected: dict,
    graph_id: str,
    *,
    require_iteration: bool = True,
):
    parameters = json.loads((checkpoint_dir / "parameters.json").read_text())
    parameter_keys = (
        "schema_version",
        "kind",
        "kernel_version",
        "history",
        "state_count",
        "columns",
        "graph_identity",
        "z_numerator",
        "z_denominator",
        "weight_scale",
        "witness_scale",
        "target_numerator",
        "target_denominator",
    )
    immutable = {key: parameters[key] for key in parameter_keys}
    require(
        hashlib.sha256(canonical_json(immutable).encode()).hexdigest()
        == parameters["parameter_sha256"],
        "checkpoint parameter hash mismatch",
    )
    require(parameters["graph_identity"] == graph_id, "checkpoint graph identity mismatch")
    for key in ("history", "state_count", "columns", "witness_scale"):
        require(parameters[key] == expected[key], f"checkpoint {key} mismatch")
    require(parameters["weight_scale"] == WEIGHT_SCALE, "weight scale mismatch")
    require(
        (parameters["z_numerator"], parameters["z_denominator"]) == (3209, 10000),
        "z mismatch",
    )
    latest = json.loads((checkpoint_dir / "latest.json").read_text())
    if require_iteration:
        require(latest["iteration"] == expected["iteration"], "checkpoint iteration mismatch")
    state_path = checkpoint_dir / latest["state_file"]
    digest = sha256_file(state_path)
    require(digest == latest["state_sha256"], "latest state hash mismatch")
    require(digest == expected["state_sha256"], "expected state hash mismatch")
    witness = np.load(state_path, allow_pickle=False, mmap_mode="r")
    require(witness.dtype == np.uint32, "witness dtype mismatch")
    require(witness.shape == (expected["state_count"],), "witness shape mismatch")
    return parameters, latest, witness


def validate_expected_diagnostics(label: str, result: dict) -> None:
    expected = EXPECTED[label]
    for key in (
        "iteration",
        "lambda_numerator",
        "lambda_floor",
        "ratio_width_units",
        "state_min",
        "state_max",
    ):
        require(result[key] == expected[key], f"{label} {key} mismatch")


def certify(
    label: str,
    graph_dir: Path,
    checkpoint_dir: Path,
    *,
    check_expected_diagnostics: bool = True,
) -> dict:
    expected = EXPECTED[label]
    print(f"[{label}] authenticating graph and checkpoint", flush=True)
    manifest, transitions = authenticate_graph(graph_dir, expected)
    parameters, latest, witness = authenticate_checkpoint(
        checkpoint_dir,
        expected,
        expected["graph_identity"],
        require_iteration=check_expected_diagnostics,
    )
    z = Fraction(parameters["z_numerator"], parameters["z_denominator"])
    weights, errors = upward_weights(expected["history"], z)
    require(weights.size == expected["columns"], "weight column count mismatch")
    state_min = int(witness.min())
    state_max = int(witness.max())
    require(state_min > 0, f"{label} witness is not strictly positive")
    require(
        state_max <= expected["witness_scale"],
        f"{label} witness exceeds its declared scale",
    )
    worst_row = int(weights.sum()) * expected["witness_scale"]
    require(worst_row + expected["witness_scale"] - 1 <= UINT64_MAX, "uint64 preflight failed")
    pinned_lambda = int(expected["lambda_numerator"])
    require(
        pinned_lambda * expected["state_max"] <= UINT64_MAX,
        "pinned lambda product preflight failed",
    )

    raw = np.empty(expected["state_count"], dtype=np.uint64)
    numba.set_num_threads(min(18, numba.config.NUMBA_NUM_THREADS))
    started = time.perf_counter()
    apply_integer_operator(transitions, weights, witness, raw)
    invalid_successor_row = int(first_invalid_successor_row(raw))
    require(
        invalid_successor_row == -1,
        f"{label} successor closure failure at state {invalid_successor_row}",
    )
    lambda_numerator, lambda_floor, failing_state = scan_integer_ratios(
        raw, witness, np.uint64(pinned_lambda)
    )
    elapsed = time.perf_counter() - started
    result = {
        "history": expected["history"],
        "states": expected["state_count"],
        "iteration": int(latest["iteration"]),
        "lambda_numerator": int(lambda_numerator),
        "lambda_denominator": WEIGHT_SCALE,
        "lambda_floor": int(lambda_floor),
        "ratio_width_units": int(lambda_numerator - lambda_floor),
        "failing_state": int(failing_state),
        "state_min": state_min,
        "state_max": state_max,
        "raw_max": int(raw.max()),
        "maximum_full_row_sum": worst_row,
        "weight_error_maximum": errors["maximum"],
        "weight_error_sum": errors["sum"],
        "scan_seconds": elapsed,
        "state_sha256": latest["state_sha256"],
        "graph_identity": graph_identity(manifest),
    }
    if check_expected_diagnostics:
        validate_expected_diagnostics(label, result)
    require(
        result["failing_state"] == -1,
        f"{label} feasibility failure: state {result['failing_state']} violates "
        f"S_i <= {pinned_lambda}/2^32 * V_i",
    )
    print(
        f"[{label}] exact feasibility PASS: lambda={result['lambda_numerator']}/2^32 "
        f"width={result['ratio_width_units']} scan={elapsed:.2f}s",
        flush=True,
    )
    return result


def tamper_control(graph_dir: Path, checkpoint_dir: Path) -> dict:
    """Adversarial control: a corrupted witness must be rejected.

    Halve one witness coordinate, recompute the operator on the tampered
    vector, and require the per-state feasibility scan to find a violating
    state.  This exercises the same code path that certifies the record, so a
    checker that silently accepts anything would fail here.
    """
    expected = EXPECTED["calibration"]
    manifest, transitions = authenticate_graph(graph_dir, expected)
    _parameters, _latest, witness = authenticate_checkpoint(
        checkpoint_dir, expected, expected["graph_identity"]
    )
    z = Fraction(3209, 10000)
    weights, _errors = upward_weights(expected["history"], z)
    pinned_lambda = np.uint64(expected["lambda_numerator"])

    tampered = np.array(witness, copy=True)
    victim = int(np.argmax(tampered))
    original = int(tampered[victim])
    require(original >= 2, "tamper control needs a witness value >= 2")
    tampered[victim] = original // 2

    raw = np.empty(expected["state_count"], dtype=np.uint64)
    apply_integer_operator(transitions, weights, tampered, raw)
    _ceiling, _floor, failing = scan_integer_ratios(raw, tampered, pinned_lambda)
    require(int(failing) >= 0, "tamper control did NOT reject a corrupted witness")
    print(
        f"[tamper] PASS: corrupting witness[{victim}] {original} -> {original // 2} "
        f"is rejected at state {int(failing)}",
        flush=True,
    )
    return {
        "victim_state": victim,
        "original_value": original,
        "tampered_value": original // 2,
        "rejected_at_state": int(failing),
        "status": "PASS",
    }


def verify_log_and_rescale(checkpoint_root: Path) -> dict:
    entries = {8: [], 10: []}
    for line in (ROOT / "LOG.md").read_text().splitlines():
        if " upper-sweep `" not in line:
            continue
        record = json.loads(line.split("`", 2)[1])
        if record.get("history") not in entries:
            continue
        sweep_id = record.pop("sweep_id")
        require(
            hashlib.sha256(canonical_json(record).encode()).hexdigest() == sweep_id,
            "sweep ID mismatch",
        )
        record["sweep_id"] = sweep_id
        entries[record["history"]].append(record)
    for history, final_iteration in ((8, 203), (10, 113)):
        records = entries[history]
        require(
            [record["iteration"] for record in records] == list(range(1, final_iteration + 1)),
            f"h={history} iteration sequence mismatch",
        )
        require(len({record["sweep_id"] for record in records}) == len(records), "duplicate sweep ID")
        require(all(record["feasible"] for record in records), f"h={history} infeasible log entry")

    h10 = entries[10]
    for index in range(1, 100):
        require(
            h10[index]["source_state_sha256"] == h10[index - 1]["state_sha256"],
            "low-precision state chain mismatch",
        )
    for index in range(101, 113):
        require(
            h10[index]["source_state_sha256"] == h10[index - 1]["state_sha256"],
            "high-precision state chain mismatch",
        )
    require(all(record["witness_scale"] == 1 << 26 for record in h10[:100]), "Q26 segment mismatch")
    require(all(record["witness_scale"] == 1 << 31 for record in h10[100:]), "Q31 segment mismatch")

    parent_latest = json.loads((checkpoint_root / "upper-h10/latest.json").read_text())
    child_parameters = json.loads((checkpoint_root / "upper-h10-q31/parameters.json").read_text())
    require(parent_latest["iteration"] == child_parameters["parent_iteration"] == 100, "rescale iteration mismatch")
    require(
        parent_latest["state_sha256"] == child_parameters["parent_state_sha256"],
        "rescale parent hash mismatch",
    )
    require(child_parameters["rescale_factor"] == 32, "rescale factor mismatch")

    parent = np.load(
        checkpoint_root / "upper-h10" / parent_latest["state_file"],
        allow_pickle=False,
        mmap_mode="r",
    )
    final_latest = json.loads((checkpoint_root / "upper-h10-q31/latest.json").read_text())
    final_state = np.load(
        checkpoint_root / "upper-h10-q31" / final_latest["state_file"],
        allow_pickle=False,
        mmap_mode="r",
    )
    with Path(final_state.filename).open("rb") as handle:
        header = handle.read(final_state.offset)
    digest = hashlib.sha256(header)
    for start in range(0, parent.size, 4_000_000):
        scaled = (parent[start : start + 4_000_000].astype(np.uint64) * 32).astype(np.uint32)
        digest.update(scaled.tobytes(order="C"))
    child_hash = digest.hexdigest()
    require(child_hash == h10[100]["source_state_sha256"], "rescaled child hash mismatch")
    return {"h8_sweeps": 203, "h10_sweeps": 113, "rescaled_child_sha256": child_hash}


def verify_benchmark(graph_root: Path) -> dict:
    benchmark = json.loads((ROOT / "upper-benchmark-results.json").read_text())
    require(benchmark["required_reserve_bytes"] == 20 * (1 << 30), "reserve mismatch")
    require(benchmark["selected_maximum_history"] == 10, "selected history mismatch")
    selected = next(item for item in benchmark["results"] if item["history"] == 10)
    require(selected["reserve_pass"], "h=10 reserve gate failed")
    require(selected["graph_identity"] == EXPECTED["record"]["graph_identity"], "benchmark graph mismatch")
    require(selected["state_count"] == EXPECTED["record"]["state_count"], "benchmark count mismatch")
    require(
        selected["minimum_measured_available_bytes"] >= benchmark["required_reserve_bytes"],
        "measured reserve violated",
    )
    rejected = benchmark["first_rejected_scale"]
    require(rejected["history"] == 11, "first rejected history mismatch")
    require(rejected["status"] == "REJECTED_BUILDER_PREFLIGHT", "h=11 rejection mismatch")
    require(
        rejected["reserve_deficit_bytes"]
        == benchmark["required_reserve_bytes"] - rejected["projected_headroom_bytes"],
        "reserve deficit arithmetic mismatch",
    )
    require(not (graph_root / "h11").exists(), "rejected h=11 graph unexpectedly exists")
    return {
        "selected_history": 10,
        "minimum_available_bytes": selected["minimum_measured_available_bytes"],
        "h11_reserve_deficit_bytes": rejected["reserve_deficit_bytes"],
    }


def verify_saved_certificate(record: dict) -> None:
    path = ROOT / "upper-h10-certificate.json"
    require(sha256_file(path) == CERTIFICATE_SHA256, "saved certificate hash mismatch")
    saved = json.loads(path.read_text())
    checks = {
        "status": "PASS",
        "feasible": True,
        "failing_state": -1,
        "target_pass": True,
        "iteration": 113,
        "graph_identity": record["graph_identity"],
        "state_sha256": record["state_sha256"],
        "lambda_numerator": record["lambda_numerator"],
        "lambda_denominator": WEIGHT_SCALE,
        "lambda_floor": record["lambda_floor"],
        "ratio_width_units": record["ratio_width_units"],
        "stored_state_error_units": 0,
        "integer_sum_error_units": 0,
        "feasibility_comparison_error_units": 0,
        "overflow_preflight": True,
    }
    for key, value in checks.items():
        require(saved[key] == value, f"saved certificate {key} mismatch")
    require(
        Fraction(saved["weight_error_max_numerator"], saved["weight_error_max_denominator"])
        == record["weight_error_maximum"],
        "saved maximum weight error mismatch",
    )
    require(
        Fraction(saved["weight_error_sum_numerator"], saved["weight_error_sum_denominator"])
        == record["weight_error_sum"],
        "saved total weight error mismatch",
    )


def verify_certificate_claim(graph_root: Path, checkpoint_root: Path) -> dict:
    """Run only the checks whose truth decides the mathematical claim."""

    record = certify(
        "record",
        graph_root / "h10",
        checkpoint_root / "upper-h10-q31",
        check_expected_diagnostics=False,
    )
    claimed_pass, claimed_terms = exact_target_decision(
        Fraction(3209, 10000), record["lambda_numerator"], 824443, 1_000_000
    )
    require(claimed_pass, "claimed 0.824443 target failed")
    require(824443 < 826280, "record comparison is not strict")
    return {
        "record": record,
        "record_target_log_terms": claimed_terms,
    }


def verify_optional_provenance(
    record: dict, graph_root: Path, checkpoint_root: Path
) -> dict:
    """Validate reproducibility evidence that is not a proof premise."""

    source_paper = ROOT / "sources/papers/lueker-2009.pdf"
    # The primary source is ACM-copyrighted and is therefore not redistributed
    # here.  If a local copy is present we authenticate it byte-for-byte; if not
    # we say so.  The theorem does not depend on the PDF: it is provenance for
    # the formulation in UPPER_FORMULATION.md.
    if source_paper.is_file():
        require(sha256_file(source_paper) == PAPER_SHA256, "paper hash mismatch")
        source_paper_authenticated = True
        print("[source] frozen Lueker paper authenticated", flush=True)
    else:
        source_paper_authenticated = False
        print(
            "[source] Lueker 2009 PDF absent (not redistributed); run "
            "scripts/fetch_source_paper.sh to authenticate it",
            flush=True,
        )
    benchmark = verify_benchmark(graph_root)
    calibration = certify(
        "calibration", graph_root / "h8", checkpoint_root / "upper-calibration-h8"
    )
    calibration_pass, calibration_terms = exact_target_decision(
        Fraction(3209, 10000), calibration["lambda_numerator"], 826280, 1_000_000
    )
    require(calibration_pass, "published 0.826280 calibration target failed")
    calibration_sharp, _ = exact_target_decision(
        Fraction(3209, 10000), calibration["lambda_numerator"], 826279, 1_000_000
    )
    require(
        not calibration_sharp,
        "h=8 witness unexpectedly proves better than Lueker's published 0.826280; "
        "the calibration gate is not sharp and the pipeline may be biased",
    )
    tamper = tamper_control(
        graph_root / "h8", checkpoint_root / "upper-calibration-h8"
    )
    internal_pass, internal_terms = exact_target_decision(
        Fraction(3209, 10000), record["lambda_numerator"], 826279, 1_000_000
    )
    next_lower_pass, next_lower_terms = exact_target_decision(
        Fraction(3209, 10000), record["lambda_numerator"], 824442, 1_000_000
    )
    require(internal_pass, "checkpoint target failed")
    require(not next_lower_pass, "unexpected 0.824442 target passage")
    validate_expected_diagnostics("record", record)
    verify_saved_certificate(record)
    log = verify_log_and_rescale(checkpoint_root)
    return {
        "source_paper_authenticated": source_paper_authenticated,
        "calibration": calibration,
        "calibration_log_terms": calibration_terms,
        "internal_target_log_terms": internal_terms,
        "next_lower_target_log_terms": next_lower_terms,
        "benchmark": benchmark,
        "log": log,
        "tamper_control": tamper,
        "saved_certificate_authenticated": True,
    }


def artifact_paths(
    with_provenance: bool, graph_root: Path, checkpoint_root: Path
) -> list[Path]:
    artifacts: list[Path] = []
    directories = [graph_root / "h10", checkpoint_root / "upper-h10-q31"]
    if with_provenance:
        artifacts.extend(
            [
                ROOT / "upper-benchmark-results.json",
                ROOT / "upper-h10-certificate.json",
                ROOT / "LOG.md",
            ]
        )
        directories.extend(
            [
                graph_root / "h8",
                checkpoint_root / "upper-calibration-h8",
                checkpoint_root / "upper-h10",
            ]
        )
        source_paper = ROOT / "sources/papers/lueker-2009.pdf"
        if source_paper.is_file():
            artifacts.append(source_paper)
    for directory in directories:
        require(directory.is_dir(), f"required artifact directory is absent: {directory}")
        artifacts.extend(sorted(path for path in directory.iterdir() if path.is_file()))
    return artifacts


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-root", type=Path, default=ROOT / "upper_graphs")
    parser.add_argument("--checkpoint-root", type=Path, default=ROOT / "checkpoints")
    parser.add_argument(
        "--with-provenance",
        action="store_true",
        help="also validate logs, rescale lineage, calibration, benchmark, and source hashes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    graph_root = args.graph_root.resolve()
    checkpoint_root = args.checkpoint_root.resolve()
    artifacts = artifact_paths(args.with_provenance, graph_root, checkpoint_root)
    before = snapshot(artifacts)
    started = time.perf_counter()

    certificate = verify_certificate_claim(graph_root, checkpoint_root)
    record = certificate["record"]
    provenance = (
        verify_optional_provenance(record, graph_root, checkpoint_root)
        if args.with_provenance
        else {"status": "NOT_RUN", "reason": "optional; pass --with-provenance"}
    )

    after = snapshot(artifacts)
    require(after == before, "verifier modified a certificate artifact")
    elapsed = time.perf_counter() - started
    bound_approx = 2 * math.log(2 * 0.3209) / math.log(record["lambda_numerator"] / WEIGHT_SCALE)
    summary = {
        "status": "PASS",
        "read_only": True,
        "proof_critical_scope": "PASS",
        "optional_provenance_scope": "PASS" if args.with_provenance else "NOT_RUN",
        "published_calibration": "gamma_2 <= 826280/1000000",
        "record_bound": "gamma_2 <= 824443/1000000 < 826280/1000000",
        "record_bound_approximation": bound_approx,
        **certificate,
        "provenance": provenance,
        "wall_seconds": elapsed,
    }
    print(json.dumps(summary, indent=2, sort_keys=True, default=str), flush=True)
    print("PASS: exact feasible witness proves gamma_2 <= 0.824443 < 0.826280", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as error:
        print(f"FAIL: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
