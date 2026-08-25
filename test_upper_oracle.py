from fractions import Fraction
import unittest

from upper_oracle import (
    UpperState,
    apply_operator,
    build_automaton,
    check_rational_upper_bound,
    match_pair_weight,
    row_sums,
    transition,
    verify_feasible,
)


class UpperOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h2 = build_automaton(2)

    def test_figure_5_and_figure_6_transitions(self):
        state = UpperState(0, 4, 7, 1)
        self.assertEqual(transition(state, 1, 1, 3), UpperState(1, 1, 5, 1))
        self.assertIsNone(transition(state, 1, 2, 3))

    def test_h2_published_state_count_and_transition_table(self):
        expected_states = (
            UpperState(0b00, 0b00, 0b11, 0b11),
            UpperState(0b00, 0b10, 0b11, 0b01),
            UpperState(0b01, 0b11, 0b01, 0b11),
            UpperState(0b01, 0b01, 0b11, 0b01),
            UpperState(0b01, 0b01, 0b11, 0b11),
            UpperState(0b01, 0b01, 0b01, 0b11),
            UpperState(0b01, 0b01, 0b01, 0b01),
        )
        self.assertEqual(self.h2.states, expected_states)
        # q0 in Lueker's code overview is rejection; accepting q1..q7 become 0..6.
        expected = (
            (1, 0, 2, 3, 4, 5),
            (1, 0, None, 3, 3, 6),
            (6, 5, 5, None, 0, 2),
            (3, 3, 6, 1, 0, None),
            (3, 4, 5, 1, 0, 2),
            (6, 5, 5, None, 0, 2),
            (6, 6, 6, None, 0, None),
        )
        labels = ((0, -1), (0, 0), (0, 1), (1, -1), (1, 0), (1, 1))
        actual = tuple(tuple(row.get(label) for label in labels) for row in self.h2.transitions)
        self.assertEqual(actual, expected)

    def test_published_h3_h4_state_counts(self):
        self.assertEqual(len(build_automaton(3).states), 98)
        self.assertEqual(len(build_automaton(4).states), 1020)

    def test_grouped_match_pair_weights_are_exact(self):
        z = Fraction(1, 5)
        self.assertEqual(match_pair_weight(z, 0, 2), Fraction(1, 25))
        self.assertEqual(match_pair_weight(z, -1, 2), Fraction(1, 100))
        self.assertEqual(match_pair_weight(z, 1, 2), Fraction(1, 100))

    def test_exact_operator_and_feasible_all_ones_witness(self):
        z = Fraction(1, 5)
        witness = tuple(Fraction(1) for _ in self.h2.states)
        image = apply_operator(self.h2, z, witness)
        self.assertEqual(image, row_sums(self.h2, z))
        lam = max(image)
        result = verify_feasible(self.h2, z, witness, lam)
        self.assertTrue(result.feasible)
        self.assertEqual(result.max_ratio, lam)
        self.assertLess(lam, 1)

    def test_exact_scan_rejects_one_unit_infeasibility(self):
        z = Fraction(1, 5)
        witness = tuple(Fraction(1) for _ in self.h2.states)
        lam = max(row_sums(self.h2, z))
        result = verify_feasible(self.h2, z, witness, lam - Fraction(1, 10**9))
        self.assertFalse(result.feasible)
        self.assertIsNotNone(result.failing_state)
        self.assertGreater(result.lhs, result.rhs)

    def test_feasibility_preconditions_are_enforced(self):
        witness = tuple(Fraction(1) for _ in self.h2.states)
        with self.assertRaises(ValueError):
            verify_feasible(self.h2, Fraction(1, 2), witness, Fraction(1, 2))
        with self.assertRaises(ValueError):
            verify_feasible(self.h2, Fraction(1, 5), witness, Fraction(1))
        with self.assertRaises(ValueError):
            verify_feasible(
                self.h2,
                Fraction(1, 5),
                witness[:-1] + (Fraction(0),),
                Fraction(1, 2),
            )
        with self.assertRaises(TypeError):
            verify_feasible(self.h2, Fraction(1, 5), tuple([1] * 7), Fraction(1, 2))

    def test_log_normalization_is_exactly_algebraic(self):
        z = Fraction(1, 5)
        lam = Fraction(3, 25)
        # Exact equality: (2/5)^2 = (3/25)^0 is not useful, so exercise
        # both sides against independently computed rational powers.
        self.assertEqual(
            check_rational_upper_bound(z, lam, 1, 1),
            (Fraction(2, 5) ** 2 >= Fraction(3, 25)),
        )
        self.assertFalse(check_rational_upper_bound(z, lam, 4, 5))


if __name__ == "__main__":
    unittest.main()
