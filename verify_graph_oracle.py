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

``full``        run the structural contract and recompute every transition of
                an existing graph.  The command exists for a future h=10 run;
                no completed full-h10 result is shipped by this repository.

Usage
-----
    python3 verify_graph_oracle.py exhaustive --max-history 6
    python3 verify_graph_oracle.py sample --graph-dir upper_graphs/h10 \
        --samples 20000 --seed 20260825

The exhaustive mode is intentionally capped at h=6.  See
``docs/FULL_H10_ORACLE.md`` before attempting the full command.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time

import numba
import numpy as np

from upper_contract import (
    ContractError,
    REJECT_INDEX,
    validate_complete_graph,
)
from upper_engine import build_graph, load_graph
from upper_oracle import (
    UpperState,
    decode_state,
    encode_state,
    initial_state,
    reduce_complement,
    transition,
    transition_labels,
)


REJECT = REJECT_INDEX


def columns_for(history: int) -> list[tuple[int, int]]:
    """Declarative certificate column order, independent of the builder."""
    return list(transition_labels(history))


def encode(state: UpperState, history: int) -> int:
    return encode_state(state, history)


def decode(value: int, history: int) -> UpperState:
    return decode_state(int(value), history)


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
    if max_history < 2 or max_history > 6:
        raise SystemExit("exhaustive mode is deliberately bounded to histories 2..6")
    results = []
    for history in range(2, max_history + 1):
        started = time.perf_counter()
        graph_dir = workdir / f"h{history}"
        if not (graph_dir / "graph.json").is_file():
            build_graph(history, graph_dir)
        manifest, states, transitions = load_graph(graph_dir)
        try:
            contract = validate_complete_graph(states, transitions, history)
        except ContractError as error:
            print(json.dumps({"kind": error.code, **error.details}, indent=2))
            raise SystemExit(f"h={history}: proof contract failed: {error}") from error
        elapsed = time.perf_counter() - started
        results.append(
            {
                "history": history,
                "states": int(states.size),
                "columns": int(transitions.shape[1]),
                "rows_checked": int(states.size),
                "transitions_checked": int(states.size) * int(transitions.shape[1]),
                "contract": contract,
                "graph_identity_states_sha256": manifest["states_sha256"],
                "graph_identity_transitions_sha256": manifest["transitions_sha256"],
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
    expected_start = encode(initial_state(history), history)
    if not states.size or int(states[0]) != expected_start:
        raise SystemExit(f"h={history}: serialized start state is incorrect")
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




# ---------------------------------------------------------------- full sweep

_SHARED: dict = {}


@numba.njit
def _scan_discovery_order(transitions, state_count):
    """Validate closure and prove reachability by serialized discovery order."""
    discovered = np.zeros(state_count, dtype=np.uint8)
    discovered[0] = 1
    for source in range(state_count):
        if discovered[source] == 0:
            return source, -1, -1, int(discovered.sum())
        for column in range(transitions.shape[1]):
            successor = int(transitions[source, column])
            if successor == REJECT:
                continue
            if successor < 0 or successor >= state_count:
                return source, column, successor, int(discovered.sum())
            discovered[successor] = 1
    return -1, -1, -1, int(discovered.sum())


def validate_full_structure(states, transitions, history: int, ordered, ordering) -> dict:
    """Scalable structural contract used only by the future full-h10 run."""
    count = int(states.size)
    if count == 0 or int(states[0]) != encode(initial_state(history), history):
        raise SystemExit(f"h={history}: serialized start state is incorrect")
    if ordered.shape != (count,) or ordering.shape != (count,):
        raise SystemExit(f"h={history}: lookup index shape does not match the state set")
    previous = None
    for start in range(0, count, 4_000_000):
        stop = min(start + 4_000_000, count)
        values = np.asarray(ordered[start:stop])
        indices = np.asarray(ordering[start:stop])
        if np.any(indices < 0) or np.any(indices >= count):
            raise SystemExit(f"h={history}: lookup index contains an out-of-range row")
        if not np.array_equal(values, np.asarray(states[indices])):
            raise SystemExit(f"h={history}: lookup index does not match the state table")
        if previous is not None and values.size and int(values[0]) <= previous:
            raise SystemExit(f"h={history}: duplicate or unsorted state at sorted index {start}")
        bad_order = np.flatnonzero(values[1:] <= values[:-1])
        if bad_order.size:
            index = start + int(bad_order[0]) + 1
            raise SystemExit(f"h={history}: duplicate or unsorted state at sorted index {index}")
        if values.size:
            previous = int(values[-1])
    mask = (1 << history) - 1
    for start in range(0, count, 4_000_000):
        values = np.asarray(states[start : start + 4_000_000])
        bad = np.flatnonzero((values & mask) >= (1 << (history - 1)))
        if bad.size:
            index = start + int(bad[0])
            state = decode(states[index], history)
            if reduce_complement(state, history) != state:
                raise SystemExit(f"h={history}: noncanonical quotient state at {index}")
    source, column, successor, reached = _scan_discovery_order(transitions, count)
    if column >= 0:
        raise SystemExit(
            f"h={history}: successor {successor} at ({source}, {column}) is outside the state set"
        )
    if source >= 0:
        raise SystemExit(
            f"h={history}: state {source} was not reached before its serialized row; "
            f"only {reached} states discovered"
        )
    return {
        "history": history,
        "states": count,
        "columns": int(transitions.shape[1]),
        "start_state_index": 0,
        "start_state_correct": True,
        "state_uniqueness": True,
        "lookup_index_validated": True,
        "quotient_canonical": True,
        "successor_closure": True,
        "reachable_states": reached,
        "all_states_reachable": reached == count,
        "reachability_method": "serialized_discovery_order",
    }


def _init_worker(graph_dir: str, index_path: str, history: int) -> None:
    manifest, states, transitions = load_graph(Path(graph_dir), authenticate=False)
    base = Path(index_path)
    _SHARED["states"] = states
    _SHARED["transitions"] = transitions
    _SHARED["ordered"] = np.load(base.with_suffix(".ordered.npy"), mmap_mode="r")
    _SHARED["ordering"] = np.load(base.with_suffix(".ordering.npy"), mmap_mode="r")
    _SHARED["history"] = history
    _SHARED["columns"] = columns_for(history)


def _lookup_shared(value: int):
    ordered = _SHARED["ordered"]
    position = int(np.searchsorted(ordered, np.uint64(value)))
    if position >= ordered.size or int(ordered[position]) != value:
        return None
    return int(_SHARED["ordering"][position])


def _check_range(bounds: tuple[int, int]) -> tuple[int, int, list]:
    start, stop = bounds
    states = _SHARED["states"]
    transitions = _SHARED["transitions"]
    history = _SHARED["history"]
    columns = _SHARED["columns"]
    failures = []
    for index in range(start, stop):
        state = decode(states[index], history)
        row = transitions[index]
        for column, (character, padding) in enumerate(columns):
            successor = transition(state, character, padding, history)
            stored = int(row[column])
            if successor is None:
                if stored != REJECT:
                    failures.append({"state": index, "column": column,
                                     "kind": "stored_accepts_oracle_rejects"})
                continue
            if stored == REJECT:
                failures.append({"state": index, "column": column,
                                 "kind": "SPURIOUS_REJECT"})
                continue
            found = _lookup_shared(encode(successor, history))
            if found is None or found != stored:
                failures.append({"state": index, "column": column,
                                 "kind": "successor_mismatch", "stored": stored,
                                 "expected_index": found})
            if failures:
                return start, stop, failures[:20]
    return start, stop, failures


def run_full(graph_dir: Path, workers: int, chunk: int, index_path: Path,
             progress_path: Path | None) -> dict:
    """Recompute EVERY transition of the automaton with the oracle."""
    manifest, states, transitions = load_graph(graph_dir)
    history = int(manifest["history"])
    total = int(states.size)

    ordered_path = index_path.with_suffix(".ordered.npy")
    ordering_path = index_path.with_suffix(".ordering.npy")
    if not (ordered_path.is_file() and ordering_path.is_file()):
        print(f"[full] building sorted index over {total} states", flush=True)
        raw = np.asarray(states)
        ordering = np.argsort(raw, kind="stable").astype(np.int64)
        np.save(ordering_path, ordering)
        np.save(ordered_path, raw[ordering])
        del raw, ordering
    print(f"[full] index ready: {index_path}", flush=True)
    ordered = np.load(ordered_path, mmap_mode="r")
    ordering = np.load(ordering_path, mmap_mode="r")
    contract = validate_full_structure(states, transitions, history, ordered, ordering)

    ranges = [(i, min(i + chunk, total)) for i in range(0, total, chunk)]
    started = time.perf_counter()
    done = 0
    failures: list = []
    ctx = mp.get_context("fork")
    with ctx.Pool(
        workers, initializer=_init_worker,
        initargs=(str(graph_dir), str(index_path), history),
    ) as pool:
        for start, stop, chunk_failures in pool.imap_unordered(_check_range, ranges):
            done += stop - start
            if chunk_failures:
                failures.extend(chunk_failures)
                print(json.dumps(chunk_failures[:5], indent=2), flush=True)
                pool.terminate()
                break
            elapsed = time.perf_counter() - started
            rate = done / max(elapsed, 1e-9)
            remaining = (total - done) / max(rate, 1e-9)
            line = (f"[full] {done}/{total} rows "
                    f"({100.0 * done / total:.2f}%) {rate:.0f} rows/s "
                    f"eta {remaining / 3600.0:.2f} h")
            print(line, flush=True)
            if progress_path:
                progress_path.write_text(line + "\n")
    elapsed = time.perf_counter() - started
    if failures:
        raise SystemExit(f"h={history}: {len(failures)} transition mismatches")
    return {
        "mode": "full",
        "history": history,
        "states": total,
        "columns": int(transitions.shape[1]),
        "rows_checked": total,
        "transitions_checked": total * int(transitions.shape[1]),
        "workers": workers,
        "seconds": elapsed,
        "contract": {
            **contract,
            "rows_checked": total,
            "transitions_checked": total * int(transitions.shape[1]),
            "spurious_rejections": 0,
            "missing_successors": 0,
            "transition_mismatches": 0,
            "reference_complete": True,
        },
        "graph_identity_states_sha256": manifest["states_sha256"],
        "graph_identity_transitions_sha256": manifest["transitions_sha256"],
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    ex = sub.add_parser("exhaustive")
    ex.add_argument(
        "--max-history",
        type=int,
        choices=range(2, 7),
        default=6,
        help="largest bounded history to check (2..6 only)",
    )
    ex.add_argument("--workdir", type=Path, default=Path("upper_graphs"))
    sa = sub.add_parser("sample")
    sa.add_argument("--graph-dir", type=Path, required=True)
    sa.add_argument("--samples", type=int, default=20000)
    sa.add_argument("--seed", type=int, default=20260825)
    sa.add_argument("--output", type=Path)
    fu = sub.add_parser("full")
    fu.add_argument("--graph-dir", type=Path, required=True)
    fu.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    fu.add_argument("--chunk", type=int, default=200_000)
    fu.add_argument("--index", type=Path, default=Path("oracle-index.npz"))
    fu.add_argument("--progress", type=Path)
    fu.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.mode == "exhaustive":
        payload = run_exhaustive(args.max_history, args.workdir)
    elif args.mode == "full":
        payload = run_full(args.graph_dir, args.workers, args.chunk, args.index,
                           args.progress)
        if args.output:
            args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        payload = run_sample(args.graph_dir, args.samples, args.seed)
        if args.output:
            args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
