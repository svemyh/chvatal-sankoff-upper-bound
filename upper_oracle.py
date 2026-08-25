"""Exact reference model for Lueker's finite-history upper-bound machine.

This module intentionally favors a direct transcription of Figure 7 in Lueker
(JACM 56(3), 2009) over speed.  It is the small-history oracle against which the
production implementation is tested.  Every certificate calculation uses
``fractions.Fraction``; floating point is not accepted at this layer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True, order=True)
class UpperState:
    """The state ``(x, y, dx, dy)`` from paper Section 3.2."""

    x: int
    y: int
    dx: int
    dy: int


@dataclass(frozen=True)
class UpperAutomaton:
    """Reachable accepting states and their nonrejecting transitions."""

    history: int
    states: tuple[UpperState, ...]
    transitions: tuple[Mapping[tuple[int, int], int], ...]


@dataclass(frozen=True)
class FeasibilityResult:
    """Exact result of scanning all componentwise inequalities."""

    feasible: bool
    lambda_value: Fraction
    max_ratio: Fraction
    failing_state: int | None
    lhs: Fraction | None
    rhs: Fraction | None


def _bits(value: int, width: int) -> list[int]:
    return [(value >> shift) & 1 for shift in range(width - 1, -1, -1)]


def _suffix(bits: Sequence[int], width: int) -> int:
    value = 0
    for bit in bits[-width:]:
        value = (value << 1) | bit
    return value


def _encode_vertical(table: Sequence[Sequence[int]], i: int, j: int, h: int) -> int:
    value = 0
    for ii in range(i - h + 1, i + 1):
        difference = table[ii][j] - table[ii - 1][j]
        if difference not in (0, 1):
            raise AssertionError("vertical LCS difference is not a bit")
        value = (value << 1) | difference
    return value


def _encode_horizontal(table: Sequence[Sequence[int]], i: int, j: int, h: int) -> int:
    value = 0
    for jj in range(j - h + 1, j + 1):
        difference = table[i][jj] - table[i][jj - 1]
        if difference not in (0, 1):
            raise AssertionError("horizontal LCS difference is not a bit")
        value = (value << 1) | difference
    return value


def reduce_complement(state: UpperState, history: int) -> UpperState:
    """Use only Lueker's proved simultaneous-complement symmetry."""

    if state.x < (1 << (history - 1)):
        return state
    mask = (1 << history) - 1
    return UpperState(mask - state.x, mask - state.y, state.dx, state.dy)


def transition(
    state: UpperState,
    character: int,
    padding: int,
    history: int,
    *,
    reduce: bool = True,
) -> UpperState | None:
    """Evaluate Figure 7 exactly for one truncated minimal match pair.

    ``padding > 0`` appends that many copies of the opposite character to
    the top string; ``padding < 0`` appends them to the bottom string.  A
    return value of ``None`` is Lueker's rejecting state.
    """

    h = history
    if h < 2:
        raise ValueError("history must be at least 2")
    if character not in (0, 1):
        raise ValueError("character must be 0 or 1")
    if not -(h - 1) <= padding <= h - 1:
        raise ValueError("padding is outside the truncated alphabet")

    top = _bits(state.x, h)
    bottom = _bits(state.y, h)
    size = 2 * h + 1
    lcs = [[0] * size for _ in range(size)]
    lcs[h][h] = h

    dx = state.dx
    for i in range(h, 0, -1):
        lcs[i - 1][h] = lcs[i][h] - (dx & 1)
        dx >>= 1
    dy = state.dy
    for j in range(h, 0, -1):
        lcs[h][j - 1] = lcs[h][j] - (dy & 1)
        dy >>= 1

    opposite = 1 - character
    if padding > 0:
        top.extend([opposite] * padding)
    elif padding < 0:
        bottom.extend([opposite] * (-padding))
    top.append(character)
    bottom.append(character)
    top_len = len(top)
    bottom_len = len(bottom)

    for j in range(h + 1, bottom_len + 1):
        lcs[0][j] = lcs[0][j - 1]
    for i in range(h + 1, top_len + 1):
        lcs[i][0] = lcs[i - 1][0]
    for i in range(1, top_len + 1):
        for j in range(1, bottom_len + 1):
            if i <= h and j <= h:
                continue
            if top[i - 1] == bottom[j - 1]:
                lcs[i][j] = lcs[i - 1][j - 1] + 1
            else:
                lcs[i][j] = max(lcs[i - 1][j], lcs[i][j - 1])

    i, j = top_len, bottom_len
    matches = 0
    while i >= h and j >= h:
        if lcs[i][j] == lcs[i - 1][j]:
            i -= 1
        elif lcs[i][j] == lcs[i][j - 1]:
            j -= 1
        elif lcs[i][j] == lcs[i - 1][j - 1] + 1:
            i -= 1
            j -= 1
            matches += 1
        else:  # pragma: no cover - an internal recurrence invariant
            raise AssertionError("inconsistent LCS table")
        if i == h and j == h:
            if matches != 1:
                raise AssertionError("accepted transition did not consume one match")
            result = UpperState(
                _suffix(top, h),
                _suffix(bottom, h),
                _encode_vertical(lcs, top_len, bottom_len, h),
                _encode_horizontal(lcs, top_len, bottom_len, h),
            )
            return reduce_complement(result, h) if reduce else result
    return None


def build_automaton(history: int) -> UpperAutomaton:
    """Enumerate all reachable accepting states by breadth-first search."""

    if history < 2:
        raise ValueError("history must be at least 2")
    mask = (1 << history) - 1
    start = UpperState(0, 0, mask, mask)
    states = [start]
    numbers = {start: 0}
    rows: list[dict[tuple[int, int], int] | None] = [None]
    queue: deque[UpperState] = deque([start])
    while queue:
        state = queue.popleft()
        row: dict[tuple[int, int], int] = {}
        for character in (0, 1):
            for padding in range(-(history - 1), history):
                successor = transition(state, character, padding, history)
                if successor is None:
                    continue
                number = numbers.get(successor)
                if number is None:
                    number = len(states)
                    numbers[successor] = number
                    states.append(successor)
                    rows.append(None)
                    queue.append(successor)
                row[(character, padding)] = number
        rows[numbers[state]] = row
    if any(row is None for row in rows):  # pragma: no cover - BFS invariant
        raise AssertionError("unprocessed state")
    return UpperAutomaton(history, tuple(states), tuple(rows))  # type: ignore[arg-type]


def match_pair_weight(z: Fraction, padding: int, history: int) -> Fraction:
    """Return equation (36)'s exact grouped weight for ``T[c,padding]``."""

    if not isinstance(z, Fraction):
        raise TypeError("z must be fractions.Fraction")
    if not 0 < z < 1:
        raise ValueError("z must lie in (0,1)")
    absolute = abs(padding)
    if absolute > history - 1:
        raise ValueError("padding is outside the truncated alphabet")
    if absolute == history - 1:
        return z ** (history + 1) / (1 - z)
    return z ** (absolute + 2)


def apply_operator(
    automaton: UpperAutomaton,
    z: Fraction,
    witness: Sequence[Fraction],
) -> tuple[Fraction, ...]:
    """Compute ``A_z witness`` exactly, including rejected transitions as zero."""

    if len(witness) != len(automaton.states):
        raise ValueError("witness length does not match accepting-state count")
    if any(not isinstance(value, Fraction) for value in witness):
        raise TypeError("all witness entries must be fractions.Fraction")
    weights = {
        padding: match_pair_weight(z, padding, automaton.history)
        for padding in range(-(automaton.history - 1), automaton.history)
    }
    result = []
    for row in automaton.transitions:
        total = Fraction(0)
        for (_, padding), successor in row.items():
            total += weights[padding] * witness[successor]
        result.append(total)
    return tuple(result)


def verify_feasible(
    automaton: UpperAutomaton,
    z: Fraction,
    witness: Sequence[Fraction],
    lambda_value: Fraction,
) -> FeasibilityResult:
    """Check positivity and every inequality ``A_z v <= lambda*v`` exactly."""

    if not isinstance(z, Fraction) or not isinstance(lambda_value, Fraction):
        raise TypeError("z and lambda_value must be fractions.Fraction")
    if not 0 < z < Fraction(1, 2):
        raise ValueError("binary upper certificates require 0 < z < 1/2")
    if not 0 < lambda_value < 1:
        raise ValueError("lambda_value must lie in (0,1)")
    if len(witness) != len(automaton.states):
        raise ValueError("witness length does not match accepting-state count")
    if any(not isinstance(value, Fraction) for value in witness):
        raise TypeError("all witness entries must be fractions.Fraction")
    if any(value <= 0 for value in witness):
        raise ValueError("every witness entry must be strictly positive")

    image = apply_operator(automaton, z, witness)
    ratios = tuple(lhs / value for lhs, value in zip(image, witness, strict=True))
    max_ratio = max(ratios)
    for state_number, (lhs, value) in enumerate(zip(image, witness, strict=True)):
        rhs = lambda_value * value
        if lhs > rhs:
            return FeasibilityResult(
                False, lambda_value, max_ratio, state_number, lhs, rhs
            )
    return FeasibilityResult(True, lambda_value, max_ratio, None, None, None)


def check_rational_upper_bound(
    z: Fraction,
    lambda_value: Fraction,
    numerator: int,
    denominator: int,
) -> bool:
    """Check Theorem 3.3's logarithmic normalization without logarithms.

    Because ``2*z`` and ``lambda_value`` both lie in ``(0,1)``, the claim

        2 log(2z) / log(lambda_value) <= numerator / denominator

    is equivalent to

        (2z) ** (2*denominator) >= lambda_value ** numerator.
    """

    if not isinstance(z, Fraction) or not isinstance(lambda_value, Fraction):
        raise TypeError("z and lambda_value must be fractions.Fraction")
    if not 0 < z < Fraction(1, 2):
        raise ValueError("z must lie in (0,1/2)")
    if not 0 < lambda_value < 1:
        raise ValueError("lambda_value must lie in (0,1)")
    if numerator <= 0 or denominator <= 0:
        raise ValueError("bound numerator and denominator must be positive")
    return (2 * z) ** (2 * denominator) >= lambda_value**numerator


def row_sums(
    automaton: UpperAutomaton, z: Fraction
) -> tuple[Fraction, ...]:
    """Convenience values for the exact all-ones witness."""

    ones = tuple(Fraction(1) for _ in automaton.states)
    return apply_operator(automaton, z, ones)

