from fractions import Fraction
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

from upper_engine import (
    REJECT,
    WEIGHT_SCALE,
    WITNESS_SCALE,
    apply_fixed,
    build_graph,
    builder_sizing_plan,
    decode_state,
    exact_log_interval,
    exact_ratio_scan,
    exact_target_check,
    load_checkpoint,
    load_graph,
    normalize_fixed,
    certify_checkpoint,
    compile_graph_builder,
    rescale_checkpoint,
    run,
    sha256_file,
    upward_weights,
)
from upper_oracle import UpperState, apply_operator, build_automaton
from upper_matrix_free import CompactMatrixFreeIndex, MatrixFreeIndex, prove_equivalence
from upper_h11_run import compile_state_builder


class UpperEngineTests(unittest.TestCase):
    def test_persistent_keyless_state_builder_resumes_byte_identically(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_dir = root / "graph"
            manifest = build_graph(4, graph_dir)
            states_path = root / "persistent-states.u64"
            index_path = root / "persistent-values.u32"
            states_path.touch()
            with index_path.open("wb") as handle:
                handle.truncate(2048 * 4)
            builder = compile_state_builder()

            first = subprocess.run(
                [
                    str(builder), "4", "1020", "2048", str(states_path),
                    str(index_path), "0", "0", "500",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )
            first_fields = dict(
                field.split("=", 1) for field in first.stdout.strip().split()
            )
            self.assertEqual(first_fields["processed"], "500")
            self.assertEqual(first_fields["complete"], "0")
            second = subprocess.run(
                [
                    str(builder), "4", "1020", "2048", str(states_path),
                    str(index_path), first_fields["processed"],
                    first_fields["states"], "100000",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )
            second_fields = dict(
                field.split("=", 1) for field in second.stdout.strip().split()
            )
            self.assertEqual(second_fields["complete"], "1")
            self.assertEqual(int(second_fields["states"]), manifest["state_count"])
            self.assertEqual(
                sha256_file(states_path), sha256_file(graph_dir / manifest["states_file"])
            )

    def test_keyless_builder_is_byte_identical_to_legacy_builder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builder = compile_graph_builder()
            normal_transitions = root / "normal-transitions.u32"
            normal_states = root / "normal-states.u64"
            keyless_transitions = root / "keyless-transitions.u32"
            keyless_states = root / "keyless-states.u64"
            normal = subprocess.run(
                [str(builder), "4", "1020", str(normal_transitions), str(normal_states)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )
            keyless = subprocess.run(
                [
                    str(builder),
                    "4",
                    "1020",
                    str(keyless_transitions),
                    str(keyless_states),
                    str((1 << 64) - 1),
                    "keyless",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )
            self.assertIn("keyless=0", normal.stdout)
            self.assertIn("keyless=1", keyless.stdout)
            self.assertEqual(sha256_file(normal_states), sha256_file(keyless_states))
            self.assertEqual(
                sha256_file(normal_transitions), sha256_file(keyless_transitions)
            )

    def test_matrix_free_rows_match_stored_graph_exhaustively(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for history in (2, 3, 4):
                graph_dir = root / f"graph-h{history}"
                manifest = build_graph(history, graph_dir)
                _manifest, states, transitions = load_graph(graph_dir)
                index = MatrixFreeIndex(
                    states, manifest, root / f"index-h{history}", threads=3
                )
                weights, _exact, _errors = upward_weights(history, Fraction(6, 25))
                rng = np.random.default_rng(31 + history)
                witness = rng.integers(
                    1, WITNESS_SCALE + 1, size=manifest["state_count"], dtype=np.uint32
                )
                stored = np.empty(witness.size, dtype=np.uint64)
                matrix_free = np.empty_like(stored)
                apply_fixed(transitions, weights, witness, stored)
                index.apply(weights, witness, matrix_free)
                np.testing.assert_array_equal(matrix_free, stored)
                compact = CompactMatrixFreeIndex(
                    states, manifest, root / f"compact-index-h{history}", threads=3
                )
                compact.apply(weights, witness, matrix_free)
                np.testing.assert_array_equal(matrix_free, stored)

    def test_matrix_free_equivalence_is_checkpointed_and_restartable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_dir = root / "graph"
            source_dir = root / "source"
            equivalence_dir = root / "equivalence"
            build_graph(3, graph_dir)
            run(
                graph_dir=graph_dir,
                checkpoint_dir=source_dir,
                z=Fraction(6, 25),
                max_iterations=2,
                tolerance_units=0,
                target_numerator=1,
                target_denominator=10,
                log_path=root / "source.log",
                threads=2,
            )
            arguments = dict(
                graph_dir=graph_dir,
                index_dir=root / "index",
                source_checkpoint=source_dir,
                checkpoint_dir=equivalence_dir,
                iterations=2,
                output=root / "proof.json",
                log_path=root / "equivalence.log",
                threads=3,
            )
            first = prove_equivalence(**arguments)
            resumed = prove_equivalence(**arguments)
            self.assertEqual(first, resumed)
            self.assertEqual(first["status"], "PASS")
            self.assertTrue(first["all_raw_rows_bit_identical"])
            self.assertEqual(len(first["lambda_trajectory"]), 2)
            lines = (root / "equivalence.log").read_text().splitlines()
            self.assertEqual(len(lines), 2)

    def test_builder_sizing_plan_is_exact_and_exposes_next_scale_wall(self):
        h10 = builder_sizing_plan(10)
        self.assertTrue(h10["uint32_index_preflight"])
        self.assertEqual(h10["planned_live_bytes"], 16_086_928_424)
        h11 = builder_sizing_plan(11)
        self.assertTrue(h11["uint32_index_preflight"])
        self.assertEqual(h11["expected_state_hint"], 3_602_279_853)
        self.assertEqual(h11["planned_live_bytes"], 131_897_453_928)

    def test_generated_graphs_match_oracle_exhaustively(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for history in (2, 3, 4):
                graph_dir = root / f"h{history}"
                manifest = build_graph(history, graph_dir)
                _manifest, states, transitions = load_graph(graph_dir)
                oracle = build_automaton(history)
                self.assertEqual(manifest["state_count"], len(oracle.states))
                decoded = tuple(UpperState(*decode_state(int(value), history)) for value in states)
                self.assertEqual(decoded, oracle.states)
                labels = tuple(
                    (character, padding)
                    for character in (0, 1)
                    for padding in range(-(history - 1), history)
                )
                expected = np.array(
                    [
                        [row.get(label, int(REJECT)) for label in labels]
                        for row in oracle.transitions
                    ],
                    dtype=np.uint32,
                )
                np.testing.assert_array_equal(transitions, expected)

    def test_fixed_operator_dominates_exact_operator_and_scan_is_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            graph_dir = Path(temporary) / "graph"
            build_graph(3, graph_dir)
            _manifest, _states, transitions = load_graph(graph_dir)
            oracle = build_automaton(3)
            z = Fraction(6, 25)
            weights, _exact, _errors = upward_weights(3, z)
            rng = np.random.default_rng(3108)
            witness = rng.integers(1, WITNESS_SCALE + 1, size=len(oracle.states), dtype=np.uint32)
            raw = np.empty(witness.size, dtype=np.uint64)
            apply_fixed(transitions, weights, witness, raw)
            exact = apply_operator(oracle, z, tuple(Fraction(int(value)) for value in witness))
            for integer_total, rational_total in zip(raw, exact, strict=True):
                self.assertGreaterEqual(Fraction(int(integer_total), WEIGHT_SCALE), rational_total)
            lam, floor, failing = exact_ratio_scan(raw, witness)
            self.assertEqual(int(failing), -1)
            self.assertTrue(np.all(raw <= np.uint64(lam) * witness.astype(np.uint64)))
            self.assertTrue(np.any(raw > np.uint64(lam - 1) * witness.astype(np.uint64)))
            self.assertLessEqual(int(floor), int(lam))

    def test_five_fixed_sweeps_match_literal_python_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            graph_dir = Path(temporary) / "graph"
            build_graph(2, graph_dir)
            _manifest, _states, transitions = load_graph(graph_dir)
            weights, _exact, _errors = upward_weights(2, Fraction(1, 5))
            fast = np.full(7, WITNESS_SCALE, dtype=np.uint32)
            reference = [WITNESS_SCALE] * 7
            for _ in range(5):
                raw_fast = np.empty(7, dtype=np.uint64)
                next_fast = np.empty(7, dtype=np.uint32)
                apply_fixed(transitions, weights, fast, raw_fast)
                raw_reference = []
                for row in transitions:
                    total = 0
                    for column, successor in enumerate(row):
                        if successor != REJECT:
                            total += int(weights[column]) * reference[int(successor)]
                    raw_reference.append(total)
                self.assertEqual(list(map(int, raw_fast)), raw_reference)
                raw_max = max(raw_reference)
                normalize_fixed(raw_fast, next_fast, WITNESS_SCALE, raw_max)
                reference = [
                    WITNESS_SCALE
                    if value == raw_max
                    else max(1, min(WITNESS_SCALE, int(float(value) * WITNESS_SCALE / raw_max)))
                    for value in raw_reference
                ]
                self.assertEqual(list(map(int, next_fast)), reference)
                fast = next_fast

    def test_exact_log_target_matches_direct_small_power_comparison(self):
        for value in (Fraction(1, 5), Fraction(2, 5), Fraction(3, 7), Fraction(9, 10)):
            lower, upper = exact_log_interval(value, 32)
            self.assertLess(lower, upper)
            self.assertLess(upper - lower, Fraction(1, 10**10))
        cases = (
            (Fraction(1, 5), 3, 25, 4, 5),
            (Fraction(1, 5), 3, 25, 1, 1),
            (Fraction(6, 25), 7, 20, 3, 4),
        )
        for z, lambda_numerator, lambda_denominator, p, q in cases:
            direct = (2 * z) ** (2 * q) >= Fraction(lambda_numerator, lambda_denominator) ** p
            self.assertEqual(
                exact_target_check(z, lambda_numerator, lambda_denominator, p, q), direct
            )

    def test_split_resume_is_state_and_log_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_dir = root / "graph"
            build_graph(3, graph_dir)
            common = dict(
                graph_dir=graph_dir,
                z=Fraction(6, 25),
                tolerance_units=0,
                target_numerator=1,
                target_denominator=10,
                threads=2,
            )
            straight_dir = root / "straight"
            split_dir = root / "split"
            run(checkpoint_dir=straight_dir, max_iterations=5, log_path=root / "straight.log", **common)
            run(checkpoint_dir=split_dir, max_iterations=2, log_path=root / "split.log", **common)
            run(checkpoint_dir=split_dir, max_iterations=5, log_path=root / "split.log", **common)
            straight_latest = json.loads((straight_dir / "latest.json").read_text())
            split_latest = json.loads((split_dir / "latest.json").read_text())
            self.assertEqual(straight_latest["state_sha256"], split_latest["state_sha256"])
            straight_certificate = dict(straight_latest["certificate"])
            split_certificate = dict(split_latest["certificate"])
            straight_certificate.pop("apply_seconds")
            split_certificate.pop("apply_seconds")
            self.assertEqual(straight_certificate, split_certificate)
            straight_ids = [json.loads(line.split("`", 2)[1])["sweep_id"] for line in (root / "straight.log").read_text().splitlines()]
            split_ids = [json.loads(line.split("`", 2)[1])["sweep_id"] for line in (root / "split.log").read_text().splitlines()]
            # Timestamps and timing intentionally affect sweep IDs, but both paths
            # must contain exactly one sequential record per iteration.
            self.assertEqual(len(straight_ids), 5)
            self.assertEqual(len(split_ids), 5)

    def test_checkpoint_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_dir = root / "graph"
            checkpoint_dir = root / "checkpoint"
            manifest = build_graph(2, graph_dir)
            run(
                graph_dir,
                checkpoint_dir,
                Fraction(1, 5),
                1,
                0,
                1,
                10,
                root / "log",
                2,
            )
            parameters = json.loads((checkpoint_dir / "parameters.json").read_text())
            expected = {key: parameters[key] for key in parameters if key not in {"created_at", "parameter_sha256"}}
            latest = json.loads((checkpoint_dir / "latest.json").read_text())
            state_path = checkpoint_dir / latest["state_file"]
            with state_path.open("r+b") as handle:
                handle.seek(-1, 2)
                byte = handle.read(1)
                handle.seek(-1, 2)
                handle.write(bytes([byte[0] ^ 1]))
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_checkpoint(checkpoint_dir, expected)

    def test_rescale_checkpoint_is_exact_and_restartable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_dir = root / "graph"
            source_dir = root / "source"
            target_dir = root / "target"
            build_graph(2, graph_dir)
            common = dict(
                graph_dir=graph_dir,
                z=Fraction(1, 5),
                tolerance_units=0,
                target_numerator=1,
                target_denominator=10,
                threads=2,
            )
            run(
                checkpoint_dir=source_dir,
                max_iterations=2,
                log_path=root / "source.log",
                **common,
            )
            source_latest = json.loads((source_dir / "latest.json").read_text())
            source = np.load(source_dir / source_latest["state_file"])
            result = rescale_checkpoint(
                graph_dir, source_dir, target_dir, WITNESS_SCALE * 4
            )
            self.assertEqual(result["status"], "PASS")
            target_latest = json.loads((target_dir / "latest.json").read_text())
            target = np.load(target_dir / target_latest["state_file"])
            np.testing.assert_array_equal(
                target.astype(np.uint64), source.astype(np.uint64) * 4
            )
            self.assertEqual(target_latest["iteration"], source_latest["iteration"])
            before = certify_checkpoint(graph_dir, source_dir)
            after = certify_checkpoint(graph_dir, target_dir)
            self.assertEqual(before["lambda_numerator"], after["lambda_numerator"])
            self.assertEqual(before["lambda_floor"], after["lambda_floor"])
            run(
                checkpoint_dir=target_dir,
                max_iterations=3,
                log_path=root / "target.log",
                witness_scale=WITNESS_SCALE * 4,
                **common,
            )
            resumed = json.loads((target_dir / "latest.json").read_text())
            self.assertEqual(resumed["iteration"], 3)


if __name__ == "__main__":
    unittest.main()
