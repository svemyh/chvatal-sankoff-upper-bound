"""Declarative validation contract for serialized upper-bound automata.

This module deliberately depends on the pure-Python reference transition in
``upper_oracle`` and not on ``upper_engine`` or either C builder.  It validates
the finite graph properties needed to interpret a certificate: the start
state, unique canonical quotient representatives, successor closure,
reachability, and agreement with every reference transition.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Callable, Iterable, Sequence

from upper_oracle import (
    decode_state,
    encode_state,
    initial_state,
    reduce_complement,
    transition,
    transition_labels,
)


REJECT_INDEX = (1 << 32) - 1


class ContractError(ValueError):
    """A named proof-contract violation with stable machine-readable details."""

    def __init__(self, code: str, message: str, **details: int | str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class StructureReport:
    history: int
    states: int
    columns: int
    start_state_index: int
    start_state_correct: bool
    state_uniqueness: bool
    quotient_canonical: bool
    successor_closure: bool
    reachable_states: int
    all_states_reachable: bool

    def as_dict(self) -> dict[str, int | bool]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticReport:
    rows_checked: int
    transitions_checked: int
    spurious_rejections: int
    missing_successors: int
    transition_mismatches: int
    reference_complete: bool

    def as_dict(self) -> dict[str, int | bool]:
        return asdict(self)


def _shape(values) -> tuple[int, ...]:
    shape = getattr(values, "shape", None)
    if shape is None:
        if not isinstance(values, Sequence):
            raise ContractError("invalid_container", "value must be a sequence")
        return (len(values),)
    return tuple(int(value) for value in shape)


def validate_structure(states, transitions, history: int) -> StructureReport:
    """Validate representation, closure, and reachability without the builder."""

    labels = transition_labels(history)
    state_shape = _shape(states)
    transition_shape = _shape(transitions)
    if len(state_shape) != 1:
        raise ContractError("state_shape", "states must be one-dimensional")
    count = state_shape[0]
    if count == 0:
        raise ContractError("missing_start_state", "the state table is empty")
    if transition_shape != (count, len(labels)):
        raise ContractError(
            "transition_shape",
            "transition table shape does not match the state table and alphabet",
            expected_rows=count,
            expected_columns=len(labels),
        )

    encoded_start = encode_state(initial_state(history), history)
    start_positions = [
        index for index, value in enumerate(states) if int(value) == encoded_start
    ]
    if not start_positions:
        raise ContractError("missing_start_state", "the reference start state is absent")
    if len(start_positions) != 1:
        raise ContractError(
            "duplicate_start_state",
            "the reference start state occurs more than once",
            occurrences=len(start_positions),
        )
    if start_positions[0] != 0:
        raise ContractError(
            "start_state_not_first",
            "the serialized graph must number the start state as zero",
            actual_index=start_positions[0],
        )

    numbers: dict[int, int] = {}
    for index, raw in enumerate(states):
        encoded = int(raw)
        if encoded in numbers:
            raise ContractError(
                "duplicate_state",
                "two rows encode the same state",
                first_index=numbers[encoded],
                duplicate_index=index,
            )
        numbers[encoded] = index
        state = decode_state(encoded, history)
        if reduce_complement(state, history) != state:
            raise ContractError(
                "noncanonical_quotient_state",
                "state is not the canonical simultaneous-complement representative",
                state_index=index,
            )

    reachable = bytearray(count)
    reachable[0] = 1
    queue: deque[int] = deque([0])
    while queue:
        source = queue.popleft()
        for column, raw_successor in enumerate(transitions[source]):
            successor = int(raw_successor)
            if successor == REJECT_INDEX:
                continue
            if successor < 0 or successor >= count:
                raise ContractError(
                    "successor_outside_state_set",
                    "a nonrejecting transition does not name a graph state",
                    state_index=source,
                    column=column,
                    successor=successor,
                )
            if not reachable[successor]:
                reachable[successor] = 1
                queue.append(successor)

    reachable_count = sum(reachable)
    if reachable_count != count:
        first = next(index for index, value in enumerate(reachable) if not value)
        raise ContractError(
            "unreachable_state",
            "not every serialized state is reachable from the reference start state",
            first_unreachable=first,
            reachable_states=reachable_count,
        )

    return StructureReport(
        history=history,
        states=count,
        columns=len(labels),
        start_state_index=0,
        start_state_correct=True,
        state_uniqueness=True,
        quotient_canonical=True,
        successor_closure=True,
        reachable_states=count,
        all_states_reachable=True,
    )


def validate_reference_rows(
    states,
    transitions,
    history: int,
    *,
    indices: Iterable[int] | None = None,
    lookup: Callable[[int], int | None] | None = None,
) -> SemanticReport:
    """Compare selected rows with the declarative Figure 7 transition contract."""

    labels = transition_labels(history)
    count = _shape(states)[0]
    if _shape(transitions) != (count, len(labels)):
        raise ContractError("transition_shape", "transition table has the wrong shape")
    if lookup is None:
        numbers = {int(value): index for index, value in enumerate(states)}
        lookup = numbers.get
    selected = range(count) if indices is None else indices
    rows_checked = 0
    for raw_index in selected:
        index = int(raw_index)
        if index < 0 or index >= count:
            raise ContractError(
                "row_outside_state_set", "requested row is outside the graph"
            )
        state = decode_state(int(states[index]), history)
        for column, (character, padding) in enumerate(labels):
            expected_state = transition(state, character, padding, history)
            stored = int(transitions[index][column])
            if expected_state is None:
                if stored != REJECT_INDEX:
                    raise ContractError(
                        "stored_accepts_reference_rejects",
                        "stored graph accepts a reference-rejecting transition",
                        state_index=index,
                        column=column,
                        stored=stored,
                    )
                continue

            expected_encoded = encode_state(expected_state, history)
            expected_index = lookup(expected_encoded)
            if expected_index is None:
                raise ContractError(
                    "missing_successor",
                    "a reference successor is absent from the serialized state set",
                    state_index=index,
                    column=column,
                    expected_state=expected_encoded,
                )
            if stored == REJECT_INDEX:
                raise ContractError(
                    "spurious_rejection",
                    "stored graph rejects a reference-accepting transition",
                    state_index=index,
                    column=column,
                    expected_index=expected_index,
                )
            if stored != expected_index:
                raise ContractError(
                    "successor_mismatch",
                    "stored transition names the wrong reference successor",
                    state_index=index,
                    column=column,
                    stored=stored,
                    expected_index=expected_index,
                )
        rows_checked += 1

    return SemanticReport(
        rows_checked=rows_checked,
        transitions_checked=rows_checked * len(labels),
        spurious_rejections=0,
        missing_successors=0,
        transition_mismatches=0,
        reference_complete=rows_checked == count,
    )


def validate_complete_graph(states, transitions, history: int) -> dict[str, int | bool]:
    """Validate every structural and semantic proof-contract obligation."""

    structure = validate_structure(states, transitions, history)
    semantics = validate_reference_rows(states, transitions, history)
    return {**structure.as_dict(), **semantics.as_dict()}
