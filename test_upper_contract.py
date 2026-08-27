from fractions import Fraction
import unittest

import numpy as np

from upper_contract import (
    ContractError,
    REJECT_INDEX,
    validate_complete_graph,
    validate_reference_rows,
    validate_structure,
)
from upper_oracle import (
    build_automaton,
    encode_state,
    initial_state,
    reduce_complement,
    row_sums,
    transition,
    transition_labels,
    verify_feasible,
)
from verify_graph_oracle import validate_full_structure
from verify_upper import (
    apply_integer_operator,
    first_invalid_successor_row,
    make_parser,
)


class UpperProofContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.automaton = build_automaton(2)
        cls.states = np.asarray(
            [encode_state(state, 2) for state in cls.automaton.states], dtype=np.uint64
        )
        cls.transitions = np.asarray(
            [
                [row.get(label, REJECT_INDEX) for label in transition_labels(2)]
                for row in cls.automaton.transitions
            ],
            dtype=np.uint32,
        )

    def assert_contract_error(self, code, function, *args, **kwargs):
        with self.assertRaises(ContractError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def test_complete_reference_graph_satisfies_every_invariant(self):
        report = validate_complete_graph(self.states, self.transitions, 2)
        self.assertTrue(report["start_state_correct"])
        self.assertTrue(report["state_uniqueness"])
        self.assertTrue(report["quotient_canonical"])
        self.assertTrue(report["successor_closure"])
        self.assertTrue(report["all_states_reachable"])
        self.assertTrue(report["reference_complete"])
        self.assertEqual(report["rows_checked"], len(self.states))

    def test_spurious_rejection_is_rejected(self):
        transitions = self.transitions.copy()
        transitions[0, 2] = REJECT_INDEX
        self.assert_contract_error(
            "spurious_rejection",
            validate_reference_rows,
            self.states,
            transitions,
            2,
            indices=[0],
        )

    def test_reference_successor_missing_from_state_set_is_rejected(self):
        states = np.delete(self.states, 2)
        transitions = np.delete(self.transitions, 2, axis=0)
        self.assert_contract_error(
            "missing_successor",
            validate_reference_rows,
            states,
            transitions,
            2,
            indices=[0],
        )

    def test_duplicate_and_missing_start_state_are_rejected(self):
        duplicate = self.states.copy()
        duplicate[-1] = duplicate[0]
        self.assert_contract_error(
            "duplicate_start_state", validate_structure, duplicate, self.transitions, 2
        )

        missing = self.states.copy()
        missing[0] = missing[1]
        self.assert_contract_error(
            "missing_start_state", validate_structure, missing, self.transitions, 2
        )

    def test_duplicate_nonstart_state_is_rejected(self):
        states = self.states.copy()
        states[-1] = states[-2]
        self.assert_contract_error(
            "duplicate_state", validate_structure, states, self.transitions, 2
        )

    def test_successor_closure_and_reachability_are_enforced(self):
        outside = self.transitions.copy()
        outside[0, 0] = len(self.states)
        self.assert_contract_error(
            "successor_outside_state_set",
            validate_structure,
            self.states,
            outside,
            2,
        )

        disconnected = self.transitions.copy()
        disconnected[disconnected == len(self.states) - 1] = 0
        self.assert_contract_error(
            "unreachable_state",
            validate_structure,
            self.states,
            disconnected,
            2,
        )

    def test_complement_quotient_is_applied_to_reference_successors(self):
        start = initial_state(2)
        unreduced = transition(start, 0, 1, 2, reduce=False)
        reduced = transition(start, 0, 1, 2)
        self.assertIsNotNone(unreduced)
        self.assertNotEqual(unreduced, reduced)
        self.assertEqual(reduce_complement(unreduced, 2), reduced)
        expected_index = self.automaton.transitions[0][(0, 1)]
        self.assertEqual(self.automaton.states[expected_index], reduced)

    def test_exact_certificate_accepts_at_threshold_and_rejects_below_it(self):
        z = Fraction(1, 5)
        witness = tuple(Fraction(1) for _ in self.automaton.states)
        threshold = max(row_sums(self.automaton, z))
        accepted = verify_feasible(self.automaton, z, witness, threshold)
        rejected = verify_feasible(
            self.automaton, z, witness, threshold - Fraction(1, 10**9)
        )
        self.assertTrue(accepted.feasible)
        self.assertFalse(rejected.feasible)
        self.assertIsNotNone(rejected.failing_state)

    def test_provenance_validation_is_explicitly_opt_in(self):
        self.assertFalse(make_parser().parse_args([]).with_provenance)
        self.assertTrue(
            make_parser().parse_args(["--with-provenance"]).with_provenance
        )

    def test_certificate_kernel_rejects_an_out_of_range_successor(self):
        weights = np.asarray([1], dtype=np.uint64)
        witness = np.asarray([1], dtype=np.uint32)
        raw = np.empty(1, dtype=np.uint64)
        apply_integer_operator(
            np.asarray([[1]], dtype=np.uint32), weights, witness, raw
        )
        self.assertEqual(int(first_invalid_successor_row(raw)), 0)

        apply_integer_operator(
            np.asarray([[0]], dtype=np.uint32), weights, witness, raw
        )
        self.assertEqual(int(first_invalid_successor_row(raw)), -1)
        self.assertEqual(int(raw[0]), 1)

    def test_future_full_mode_reports_the_same_structural_contract(self):
        ordering = np.argsort(self.states, kind="stable")
        report = validate_full_structure(
            self.states, self.transitions, 2, self.states[ordering], ordering
        )
        self.assertTrue(report["start_state_correct"])
        self.assertTrue(report["state_uniqueness"])
        self.assertTrue(report["successor_closure"])
        self.assertTrue(report["all_states_reachable"])


if __name__ == "__main__":
    unittest.main()
