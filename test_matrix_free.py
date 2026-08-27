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
    Certificate,
    KernelError,
    VerificationError,
    authenticate_file,
    compile_kernel,
    ensure_index,
    ensure_state_table,
    exact_power_decision,
    index_capacity,
    load_witness,
    run_kernel,
    scan_chunk,
    scan_with_checkpoint,
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
        state_index, capacity, _details = ensure_index(
            self.kernel,
            root,
            states,
            history=history,
            state_count=state_count,
            state_sha256=state_sha,
            kernel_source_sha256=self.kernel_details["source_sha256"],
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
            ]
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
            state_index, capacity, _details = ensure_index(
                self.kernel,
                root,
                states,
                history=2,
                state_count=count,
                state_sha256=state_sha,
                kernel_source_sha256=self.kernel_details["source_sha256"],
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
                    ensure_index(
                        self.kernel,
                        case,
                        states,
                        history=2,
                        state_count=len(values),
                        state_sha256=sha256_file(states),
                        kernel_source_sha256=self.kernel_details["source_sha256"],
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
                )
            self.assertEqual(raised.exception.result["failure"], "missing_successor")

    def test_checkpoint_resume_covers_a_contiguous_authenticated_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _graph, states, state_index, capacity, witness_path, certificate = (
                self.make_fixture(root)
            )
            witness = np.load(witness_path, mmap_mode="r", allow_pickle=False)
            checkpoint = root / "checkpoint.json"
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
                checkpoint_path=checkpoint,
                kernel_source_sha256=self.kernel_details["source_sha256"],
                kernel_binary_sha256=self.kernel_details["binary_sha256"],
                chunk_rows=3,
                threads=2,
            )
            status, partial, progress = scan_with_checkpoint(
                **common, stop_after_chunks=1
            )
            self.assertEqual(status, "INCOMPLETE")
            self.assertEqual(partial["rows"], 3)
            self.assertEqual(progress["next_row"], 3)
            status, complete, progress = scan_with_checkpoint(**common)
            self.assertEqual(status, "PASS")
            self.assertEqual(complete["rows"], certificate.state_count)
            self.assertEqual(progress["resumed_from_row"], 3)

    def test_checkpoint_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _graph, states, state_index, capacity, witness_path, certificate = (
                self.make_fixture(root)
            )
            witness = np.load(witness_path, mmap_mode="r", allow_pickle=False)
            checkpoint = root / "checkpoint.json"
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
                checkpoint_path=checkpoint,
                kernel_source_sha256=self.kernel_details["source_sha256"],
                kernel_binary_sha256=self.kernel_details["binary_sha256"],
                chunk_rows=3,
                threads=2,
            )
            scan_with_checkpoint(**common, stop_after_chunks=1)
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            payload["chunks"][0]["rows"] = 2
            checkpoint.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(VerificationError):
                scan_with_checkpoint(**common)

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
