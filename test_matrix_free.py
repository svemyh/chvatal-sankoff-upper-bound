from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from upper_engine import build_graph, sha256_file
from verify_matrix_free import (
    KERNEL_SOURCE,
    Certificate,
    KernelError,
    VerificationError,
    authenticate_file,
    atomic_json,
    build_fresh_index,
    canonical_json,
    compile_kernel,
    ensure_state_table,
    exact_power_decision,
    index_capacity,
    load_witness,
    run_kernel,
    scan_certified_fresh,
    scan_chunk,
    _checkpoint_chain,
    sha256_bytes,
    upward_weights,
)


class MatrixFreeVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.kernel, cls.kernel_details = compile_kernel(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def make_fixture(
        self,
        root: Path,
        history: int = 2,
        witness_values: np.ndarray | None = None,
    ):
        graph_dir = root / f"h{history}"
        manifest = build_graph(history, graph_dir)
        states = graph_dir / "states.u64"
        state_count = int(manifest["state_count"])
        if witness_values is None:
            witness_values = np.ones(state_count, dtype="<u4")
        witness = root / f"h{history}-witness.npy"
        np.save(witness, witness_values, allow_pickle=False)
        state_sha = sha256_file(states)
        state_index, capacity, _details = build_fresh_index(
            self.kernel,
            root,
            states,
            history=history,
            state_count=state_count,
            state_sha256=state_sha,
            kernel_source_sha256=self.kernel_details["source_sha256"],
            kernel_binary_sha256=self.kernel_details["binary_sha256"],
        )
        certificate = Certificate(
            history=history,
            state_count=state_count,
            z=Fraction(1, 5),
            lambda_numerator=100,
            lambda_denominator=1 << 32,
            witness_scale=int(witness_values.max(initial=1)),
            target_numerator=1,
            target_denominator=1,
        )
        return graph_dir, states, state_index, capacity, witness, certificate

    def dump_transitions(
        self,
        history: int,
        states: Path,
        state_count: int,
        state_index: Path,
        capacity: int,
        output: Path,
    ):
        return run_kernel(
            [
                str(self.kernel),
                "dump",
                str(history),
                str(states),
                str(state_count),
                str(state_index),
                str(capacity),
                "0",
                str(state_count),
                "4",
                str(output),
            ],
            executable_sha256=self.kernel_details["binary_sha256"],
        )

    def test_independent_oracle_matches_every_builder_transition_through_h6(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for history in range(2, 7):
                graph_dir, states, state_index, capacity, _witness, certificate = (
                    self.make_fixture(root / f"case-{history}", history)
                )
                output = root / f"h{history}-oracle.u32"
                result = self.dump_transitions(
                    history,
                    states,
                    certificate.state_count,
                    state_index,
                    capacity,
                    output,
                )
                self.assertEqual(
                    output.read_bytes(),
                    (graph_dir / "transitions.u32").read_bytes(),
                    f"transition mismatch at h={history}",
                )
                self.assertEqual(
                    result["accepted_transitions"] + result["rejected_transitions"],
                    certificate.state_count * certificate.columns,
                )
                self.assertGreater(result["rejected_transitions"], 0)

    def test_scan_checks_every_transition_and_integer_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _graph, states, state_index, capacity, witness_path, certificate = (
                self.make_fixture(root)
            )
            witness = load_witness(witness_path, certificate.state_count)
            result = scan_chunk(
                self.kernel,
                certificate=certificate,
                states=states,
                index=state_index,
                capacity=capacity,
                witness=witness_path,
                witness_offset=witness.offset,
                weights=[1] * certificate.columns,
                start=0,
                end=certificate.state_count,
                threads=2,
                kernel_binary_sha256=self.kernel_details["binary_sha256"],
            )
            self.assertEqual(result["rows"], certificate.state_count)
            self.assertEqual(
                result["accepted_transitions"] + result["rejected_transitions"],
                certificate.state_count * certificate.columns,
            )
            self.assertEqual(result["witness_minimum"], 1)
            self.assertEqual(result["witness_maximum"], 1)

    def assert_scan_failure(
        self, expected: str, values: np.ndarray, weights, lam=100, witness_scale=None
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _graph, states, state_index, capacity, witness_path, certificate = (
                self.make_fixture(root, witness_values=values)
            )
            certificate = Certificate(
                **{
                    **certificate.__dict__,
                    "lambda_numerator": lam,
                    "witness_scale": (
                        max(1, int(values.max(initial=1)))
                        if witness_scale is None
                        else witness_scale
                    ),
                }
            )
            witness = np.load(witness_path, mmap_mode="r", allow_pickle=False)
            with self.assertRaises(KernelError) as raised:
                scan_chunk(
                    self.kernel,
                    certificate=certificate,
                    states=states,
                    index=state_index,
                    capacity=capacity,
                    witness=witness_path,
                    witness_offset=witness.offset,
                    weights=weights,
                    start=0,
                    end=certificate.state_count,
                    threads=2,
                    kernel_binary_sha256=self.kernel_details["binary_sha256"],
                )
            self.assertIsNotNone(raised.exception.result)
            self.assertEqual(raised.exception.result["failure"], expected)

    def test_zero_witness_is_rejected(self):
        values = np.ones(7, dtype="<u4")
        values[0] = 0
        self.assert_scan_failure("witness_zero", values, [1] * 6)

    def test_witness_coordinate_corruption_is_rejected(self):
        values = np.full(7, 2, dtype="<u4")
        values[0] = 1
        self.assert_scan_failure("inequality", values, [1] * 6, lam=6)

    def test_witness_value_above_declared_scale_is_rejected(self):
        values = np.ones(7, dtype="<u4")
        values[0] = 2
        self.assert_scan_failure(
            "witness_scale", values, [1] * 6, witness_scale=1
        )

    def test_row_overflow_is_detected_before_integer_narrowing(self):
        values = np.ones(7, dtype="<u4")
        self.assert_scan_failure(
            "row_overflow", values, [(1 << 64) - 1] * 6, lam=(1 << 64) - 1
        )

    def test_missing_successor_closure_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_dir = root / "graph"
            manifest = build_graph(2, graph_dir)
            original = np.fromfile(graph_dir / "states.u64", dtype="<u8")
            states = root / "incomplete-states.u64"
            original[:-1].tofile(states)
            count = len(original) - 1
            state_sha = sha256_file(states)
            state_index, capacity, _details = build_fresh_index(
                self.kernel,
                root,
                states,
                history=2,
                state_count=count,
                state_sha256=state_sha,
                kernel_source_sha256=self.kernel_details["source_sha256"],
                kernel_binary_sha256=self.kernel_details["binary_sha256"],
            )
            witness_path = root / "witness.npy"
            np.save(witness_path, np.ones(count, dtype="<u4"), allow_pickle=False)
            witness = np.load(witness_path, mmap_mode="r", allow_pickle=False)
            certificate = Certificate(
                2, count, Fraction(1, 5), 100, 1 << 32, 1, 1, 1
            )
            with self.assertRaises(KernelError) as raised:
                scan_chunk(
                    self.kernel,
                    certificate=certificate,
                    states=states,
                    index=state_index,
                    capacity=capacity,
                    witness=witness_path,
                    witness_offset=witness.offset,
                    weights=[1] * certificate.columns,
                    start=0,
                    end=count,
                    threads=2,
                    kernel_binary_sha256=self.kernel_details["binary_sha256"],
                )
            self.assertEqual(raised.exception.result["failure"], "missing_successor")
            self.assertEqual(manifest["state_count"], 7)

    def test_missing_initial_duplicate_and_noncanonical_states_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = root / "graph"
            manifest = build_graph(2, graph)
            original = np.fromfile(graph / "states.u64", dtype="<u8")
            cases = {
                "missing": original[1:],
                "duplicate": np.concatenate((original[:-1], original[:1])),
                "noncanonical": np.concatenate(
                    (original[:-1], np.asarray([1 << 8], dtype="<u8"))
                ),
            }
            for name, values in cases.items():
                case = root / name
                case.mkdir()
                states = case / "states.u64"
                values.tofile(states)
                with self.assertRaises(KernelError):
                    build_fresh_index(
                        self.kernel,
                        case,
                        states,
                        history=2,
                        state_count=len(values),
                        state_sha256=sha256_file(states),
                        kernel_source_sha256=self.kernel_details["source_sha256"],
                        kernel_binary_sha256=self.kernel_details["binary_sha256"],
                    )
            self.assertEqual(manifest["state_count"], 7)

    def test_corrupted_derived_index_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _graph, states, state_index, capacity, witness_path, certificate = (
                self.make_fixture(root)
            )
            index_values = np.memmap(state_index, dtype="<u4", mode="r+")
            index_values[:] = 0
            index_values.flush()
            witness = np.load(witness_path, mmap_mode="r", allow_pickle=False)
            with self.assertRaises(KernelError) as raised:
                scan_chunk(
                    self.kernel,
                    certificate=certificate,
                    states=states,
                    index=state_index,
                    capacity=capacity,
                    witness=witness_path,
                    witness_offset=witness.offset,
                    weights=[1] * certificate.columns,
                    start=0,
                    end=certificate.state_count,
                    threads=2,
                    kernel_binary_sha256=self.kernel_details["binary_sha256"],
                )
            self.assertEqual(raised.exception.result["failure"], "missing_successor")

    def test_certified_scan_restarts_from_zero_and_only_counts_fresh_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _graph, states, state_index, capacity, witness_path, certificate = (
                self.make_fixture(root)
            )
            witness = np.load(witness_path, mmap_mode="r", allow_pickle=False)
            progress_path = root / "progress.json"
            common = dict(
                kernel=self.kernel,
                certificate=certificate,
                states=states,
                state_sha256=sha256_file(states),
                index=state_index,
                capacity=capacity,
                witness=witness_path,
                witness_sha256=sha256_file(witness_path),
                witness_offset=witness.offset,
                weights=[1] * certificate.columns,
                progress_path=progress_path,
                kernel_source_sha256=self.kernel_details["source_sha256"],
                kernel_binary_sha256=self.kernel_details["binary_sha256"],
                chunk_rows=3,
                threads=2,
            )
            status, partial, progress = scan_certified_fresh(
                **common, stop_after_chunks=1
            )
            self.assertEqual(status, "INCOMPLETE")
            self.assertEqual(partial["rows"], 3)
            self.assertEqual(progress["next_row"], 3)
            first_nonce = json.loads(progress_path.read_text(encoding="utf-8"))[
                "invocation"
            ]["invocation_nonce"]
            status, partial_again, progress = scan_certified_fresh(
                **common, stop_after_chunks=1
            )
            self.assertEqual(status, "INCOMPLETE")
            self.assertEqual(partial_again["rows"], 3)
            self.assertEqual(progress["fresh_start_row"], 0)
            self.assertFalse(progress["cross_invocation_resume"])
            second_nonce = json.loads(progress_path.read_text(encoding="utf-8"))[
                "invocation"
            ]["invocation_nonce"]
            self.assertNotEqual(first_nonce, second_nonce)

            status, complete, progress = scan_certified_fresh(**common)
            self.assertEqual(status, "PASS")
            self.assertEqual(complete["rows"], certificate.state_count)
            self.assertEqual(progress["fresh_start_row"], 0)
            self.assertEqual(progress["fresh_chunks"], 3)

    def test_forged_full_checkpoint_cannot_bypass_a_missing_native_kernel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            certificate = Certificate(
                10,
                400_253_317,
                Fraction(3209, 10000),
                1464651560,
                1 << 32,
                1 << 31,
                824443,
                1_000_000,
            )
            weights = [1] * certificate.columns
            state_sha = "11" * 32
            witness_sha = "22" * 32
            source_sha = "33" * 32
            binary_sha = "44" * 32
            capacity = 1 << 29
            former_immutable = {
                "history": certificate.history,
                "state_count": certificate.state_count,
                "columns": certificate.columns,
                "state_sha256": state_sha,
                "witness_sha256": witness_sha,
                "witness_offset": 128,
                "index_capacity": capacity,
                "weights": weights,
                "lambda_numerator": certificate.lambda_numerator,
                "lambda_denominator": certificate.lambda_denominator,
                "witness_scale": certificate.witness_scale,
                "chunk_rows": certificate.state_count,
                "kernel_source_sha256": source_sha,
                "kernel_binary_sha256": binary_sha,
            }
            forged_chunk = {
                "start_row": 0,
                "end_row": certificate.state_count,
                "rows": certificate.state_count,
                "accepted_transitions": certificate.state_count
                * certificate.columns,
                "rejected_transitions": 0,
                "maximum_ceiling": 1464651560,
                "minimum_floor": 1464649541,
                "raw_maximum": 3145313150651095756,
                "witness_minimum": 9834007,
                "witness_maximum": 2147483648,
                "peak_rss_bytes": 1,
                "scan_seconds": 1.0,
            }
            chain = sha256_bytes(canonical_json(former_immutable).encode())
            forged_chunk["chain_sha256"] = _checkpoint_chain(chain, forged_chunk)
            progress_path = root / "forged-checkpoint.json"
            atomic_json(
                progress_path,
                {
                    "schema_version": 1,
                    "kind": "matrix-free-verification-checkpoint",
                    "immutable": former_immutable,
                    "chunks": [forged_chunk],
                    "chain_sha256": forged_chunk["chain_sha256"],
                },
            )

            with self.assertRaisesRegex(VerificationError, "native verifier is absent"):
                scan_certified_fresh(
                    root / "native-kernel-does-not-exist",
                    certificate=certificate,
                    states=root / "states-do-not-exist",
                    state_sha256=state_sha,
                    index=root / "index-does-not-exist",
                    capacity=capacity,
                    witness=root / "witness-does-not-exist",
                    witness_sha256=witness_sha,
                    witness_offset=128,
                    weights=weights,
                    progress_path=progress_path,
                    kernel_source_sha256=source_sha,
                    kernel_binary_sha256=binary_sha,
                    chunk_rows=certificate.state_count,
                    threads=1,
                )
            overwritten = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertEqual(overwritten["schema_version"], 2)
            self.assertEqual(overwritten["chunks"], [])
            self.assertFalse(overwritten["certifying_resume_supported"])

    def test_preplaced_source_named_executable_is_never_trusted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_sha = sha256_file(KERNEL_SOURCE)
            planted = root / "cache" / f"upper_matrix_free-{source_sha[:16]}"
            planted.parent.mkdir()
            planted.write_text(
                "#!/bin/sh\nprintf '%s\\n' '{\"status\":\"PASS\"}'\n",
                encoding="utf-8",
            )
            planted.chmod(0o700)

            kernel, details = compile_kernel(root)

            self.assertNotEqual(kernel, planted)
            self.assertEqual(details["status"], "COMPILED_FRESH")
            self.assertTrue(details["private_runtime_directory"])
            self.assertEqual(kernel.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(sha256_file(kernel), details["binary_sha256"])
            with self.assertRaises(KernelError):
                run_kernel([str(kernel)], executable_sha256=details["binary_sha256"])

    def test_forged_index_cache_cannot_bypass_global_state_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = root / "graph"
            build_graph(2, graph)
            original = np.fromfile(graph / "states.u64", dtype="<u8")
            existing = {int(value) for value in original}
            replacement = next(
                value
                for value in range(1 << 8)
                if value & 3 < 2 and value not in existing
            )
            cases = {
                "missing-initial": np.concatenate(
                    (original[1:], np.asarray([replacement], dtype="<u8"))
                ),
                "duplicate": np.concatenate((original[:-1], original[1:2])),
            }
            for name, values in cases.items():
                with self.subTest(name=name):
                    case = root / name
                    case.mkdir()
                    states = case / "states.u64"
                    values.tofile(states)
                    state_sha = sha256_file(states)
                    capacity = index_capacity(len(values))
                    cache = case / "cache"
                    cache.mkdir()
                    index = cache / f"states-{state_sha[:16]}-{capacity}.index.u32"
                    np.zeros(capacity, dtype="<u4").tofile(index)
                    metadata = {
                        "schema_version": 1,
                        "kind": "matrix-free-keyless-state-index",
                        "history": 2,
                        "state_count": len(values),
                        "state_sha256": state_sha,
                        "capacity": capacity,
                        "bytes": capacity * 4,
                        "kernel_source_sha256": self.kernel_details[
                            "source_sha256"
                        ],
                        "kernel_binary_sha256": self.kernel_details[
                            "binary_sha256"
                        ],
                    }
                    atomic_json(index.with_suffix(".json"), metadata)
                    with self.assertRaises(KernelError):
                        build_fresh_index(
                            self.kernel,
                            case,
                            states,
                            history=2,
                            state_count=len(values),
                            state_sha256=state_sha,
                            kernel_source_sha256=self.kernel_details[
                                "source_sha256"
                            ],
                            kernel_binary_sha256=self.kernel_details[
                                "binary_sha256"
                            ],
                        )

    def test_artifact_hash_and_npy_format_corruption_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            artifact.write_bytes(b"correct")
            with self.assertRaises(VerificationError):
                authenticate_file(artifact, 7, "0" * 64)

            witness = root / "witness.npy"
            np.save(witness, np.ones(7, dtype="<u8"), allow_pickle=False)
            with self.assertRaises(VerificationError):
                load_witness(witness, 7)

    def test_split_state_manifest_is_assembled_and_authenticated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_parts = [root / "source-0", root / "source-1"]
            source_parts[0].write_bytes(b"canonical-")
            source_parts[1].write_bytes(b"state-table")
            combined = b"canonical-state-table"
            description = {
                "bytes": len(combined),
                "sha256": hashlib.sha256(combined).hexdigest(),
                "parts": [
                    {
                        "name": source.name,
                        "bytes": source.stat().st_size,
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "url": source.resolve().as_uri(),
                    }
                    for source in source_parts
                ],
            }
            destination = root / "assembled.u64"
            ensure_state_table(destination, description)
            self.assertEqual(destination.read_bytes(), combined)
            self.assertFalse(any(root.glob(".*.partial")))

    def test_split_state_assembly_resumes_after_interrupted_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_parts = [root / "source-0", root / "source-1"]
            source_parts[0].write_bytes(b"canonical-")
            source_parts[1].write_bytes(b"state-table")
            combined = b"canonical-state-table"
            description = {
                "bytes": len(combined),
                "sha256": hashlib.sha256(combined).hexdigest(),
                "parts": [
                    {
                        "name": source.name,
                        "bytes": source.stat().st_size,
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "url": source.resolve().as_uri(),
                    }
                    for source in source_parts
                ],
            }
            destination = root / "assembled.u64"
            assembling = root / ".assembled.u64.assembling"
            assembling.write_bytes(b"canonical-sta")
            cached_part = root / ".source-1.partial"
            cached_part.write_bytes(b"state-table")

            ensure_state_table(destination, description)

            self.assertEqual(destination.read_bytes(), combined)
            self.assertFalse(assembling.exists())
            self.assertFalse(cached_part.exists())

    def test_deferred_state_manifest_fails_closed_without_local_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(VerificationError, "publication is deferred"):
                ensure_state_table(
                    Path(temporary) / "states.u64",
                    {"bytes": 8, "sha256": "0" * 64, "parts": []},
                )

    def test_direct_integer_power_bound_conversion_matches_literal_fractions(self):
        cases = [
            (Fraction(1, 5), Fraction(3, 25), 1, 1),
            (Fraction(1, 5), Fraction(1, 5), 1, 1),
            (Fraction(6, 25), Fraction(7, 20), 4, 5),
        ]
        for z, lam, numerator, denominator in cases:
            expected = (2 * z) ** (2 * denominator) >= lam**numerator
            self.assertEqual(
                exact_power_decision(
                    z,
                    lam.numerator,
                    lam.denominator,
                    numerator,
                    denominator,
                ),
                expected,
            )

    def test_weight_rounding_is_upward_and_index_capacity_stays_below_limit(self):
        certificate = Certificate(
            2, 7, Fraction(1, 5), 1, 1 << 32, 1, 1, 1
        )
        weights = upward_weights(certificate)
        self.assertEqual(len(weights), certificate.columns)
        self.assertEqual(weights[1], (1 << 32) // 25 + 1)
        capacity = index_capacity(400_253_317)
        self.assertEqual(capacity, 1 << 29)
        self.assertLess(400_253_317 * 100, capacity * 84)


if __name__ == "__main__":
    unittest.main()
