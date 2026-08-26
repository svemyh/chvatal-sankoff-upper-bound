#!/usr/bin/env python3
"""Independent oracle validation of a built automaton.

The certificate in ``verify_upper.py`` quantifies over the states of the
history-h automaton, and SHA-256 pinning authenticates the *bytes* of that
automaton, not its *semantics*.  The soundness-critical direction is a
spurious rejection: ``apply_integer_operator`` drops REJECT columns from the
row sum, so a legitimate transition wrongly marked REJECT would understate the
operator and make the certified bound look better than it is.

This script closes that gap without trusting the C builder:

``exhaustive``  rebuild the whole automaton with the pure-Python Figure 7
                oracle and compare states and every transition, for small h.

``sample``      draw uniformly random states of a large automaton, recompute
                their complete transition rows with the oracle, and compare.
                Any spurious REJECT, missing state, or wrong successor in a
                sampled row is reported and exits nonzero.

Usage
-----
    python3 verify_graph_oracle.py exhaustive --max-history 6
    python3 verify_graph_oracle.py sample --graph-dir upper_graphs/h10 \
        --samples 20000 --seed 20260825
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

from upper_engine import decode_state, load_graph, build_graph, REJECT
from upper_oracle import UpperState, build_automaton, transition


def columns_for(history: int) -> list[tuple[int, int]]:
    """Column order shared by the builder, the weights, and the oracle."""
    return [
        (character, padding)
        for character in (0, 1)
        for padding in range(-(history - 1), history)
    ]


def encode(state: UpperState, history: int) -> int:
    return (
        state.x
        | (state.y << history)
        | (state.dx << (2 * history))
        | (state.dy << (3 * history))
    )


def decode(value: int, history: int) -> UpperState:
    return UpperState(*decode_state(int(value), history))


def check_rows(
    indices: np.ndarray,
    states: np.ndarray,
    transitions: np.ndarray,
    history: int,
    *,
    lookup,
) -> list[dict]:
    """Recompute each sampled row with the oracle and diff it."""
    failures: list[dict] = []
    columns = columns_for(history)
    for index in indices:
        index = int(index)
        state = decode(states[index], history)
        for column, (character, padding) in enumerate(columns):
            successor = transition(state, character, padding, history)
            stored = int(transitions[index, column])
            if successor is None:
                if stored != REJECT:
                    failures.append(
                        {
                            "state": index,
                            "column": column,
                            "kind": "stored_accepts_oracle_rejects",
                            "stored": stored,
                        }
                    )
                continue
            # The dangerous direction: the oracle accepts, so the graph must
            # accept, and it must land on exactly the same successor state.
            if stored == REJECT:
                failures.append(
                    {
                        "state": index,
                        "column": column,
                        "kind": "SPURIOUS_REJECT",
                        "oracle_successor": encode(successor, history),
                    }
                )
                continue
            expected = encode(successor, history)
            found = lookup(expected)
            if found is None:
                failures.append(
                    {
                        "state": index,
                        "column": column,
                        "kind": "oracle_successor_absent_from_graph",
                        "oracle_successor": expected,
                    }
                )
            elif found != stored:
                failures.append(
                    {
                        "state": index,
                        "column": column,
                        "kind": "successor_mismatch",
                        "stored": stored,
                        "expected_index": found,
                    }
                )
    return failures


def make_lookup(states: np.ndarray):
    """Sorted-order lookup from encoded state to graph index."""
    ordering = np.argsort(states, kind="stable")
    ordered = states[ordering]

    def lookup(value: int):
        position = int(np.searchsorted(ordered, np.uint64(value)))
        if position >= ordered.size or int(ordered[position]) != value:
            return None
        return int(ordering[position])

    return lookup


def run_exhaustive(max_history: int, workdir: Path) -> dict:
    results = []
    for history in range(2, max_history + 1):
        started = time.perf_counter()
        automaton = build_automaton(history)
        graph_dir = workdir / f"h{history}"
        if not (graph_dir / "graph.json").is_file():
            build_graph(history, graph_dir)
        manifest, states, transitions = load_graph(graph_dir)
        if states.size != len(automaton.states):
            raise SystemExit(
                f"h={history}: state count differs "
                f"(graph {states.size}, oracle {len(automaton.states)})"
            )
        lookup = make_lookup(np.asarray(states))
        failures = check_rows(
            np.arange(states.size), states, transitions, history, lookup=lookup
        )
        if failures:
            print(json.dumps(failures[:20], indent=2))
            raise SystemExit(f"h={history}: {len(failures)} transition mismatches")
        # Every oracle state must also appear in the graph (no missing states).
        for state in automaton.states:
            if lookup(encode(state, history)) is None:
                raise SystemExit(f"h={history}: oracle state missing from graph")
        elapsed = time.perf_counter() - started
        results.append(
            {
                "history": history,
                "states": int(states.size),
                "columns": int(transitions.shape[1]),
                "rows_checked": int(states.size),
                "transitions_checked": int(states.size) * int(transitions.shape[1]),
                "seconds": elapsed,
                "status": "PASS",
            }
        )
        print(
            f"[exhaustive h={history}] PASS  states={states.size} "
            f"transitions={states.size * transitions.shape[1]} ({elapsed:.1f}s)",
            flush=True,
        )
    return {"mode": "exhaustive", "results": results, "status": "PASS"}


def run_sample(graph_dir: Path, samples: int, seed: int) -> dict:
    manifest, states, transitions = load_graph(graph_dir)
    history = int(manifest["history"])
    started = time.perf_counter()
    rng = np.random.default_rng(seed)
    indices = rng.choice(states.size, size=min(samples, states.size), replace=False)
    indices.sort()
    print(
        f"[sample h={history}] {indices.size} rows x {transitions.shape[1]} columns "
        f"from {states.size} states (seed {seed})",
        flush=True,
    )
    lookup = make_lookup(np.asarray(states))
    failures = check_rows(indices, states, transitions, history, lookup=lookup)
    elapsed = time.perf_counter() - started
    if failures:
        print(json.dumps(failures[:20], indent=2))
        raise SystemExit(f"h={history}: {len(failures)} transition mismatches")
    payload = {
        "mode": "sample",
        "history": history,
        "graph_identity_states_sha256": manifest["states_sha256"],
        "graph_identity_transitions_sha256": manifest["transitions_sha256"],
        "states": int(states.size),
        "columns": int(transitions.shape[1]),
        "seed": seed,
        "rows_checked": int(indices.size),
        "transitions_checked": int(indices.size) * int(transitions.shape[1]),
        "seconds": elapsed,
        "status": "PASS",
    }
    print(
        f"[sample h={history}] PASS  {payload['transitions_checked']} transitions "
        f"recomputed by the oracle, zero mismatches ({elapsed:.1f}s)",
        flush=True,
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    ex = sub.add_parser("exhaustive")
    ex.add_argument("--max-history", type=int, default=6)
    ex.add_argument("--workdir", type=Path, default=Path("upper_graphs"))
    sa = sub.add_parser("sample")
    sa.add_argument("--graph-dir", type=Path, required=True)
    sa.add_argument("--samples", type=int, default=20000)
    sa.add_argument("--seed", type=int, default=20260825)
    sa.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.mode == "exhaustive":
        payload = run_exhaustive(args.max_history, args.workdir)
    else:
        payload = run_sample(args.graph_dir, args.samples, args.seed)
        if args.output:
            args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
