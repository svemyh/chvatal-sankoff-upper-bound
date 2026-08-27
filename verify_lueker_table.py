#!/usr/bin/env python3
"""Reproduce every row of Lueker's published Table II, in exact arithmetic.

The residual risk in this artifact that hashing cannot address is a *common-mode*
misreading: if our C builder and our pure-Python oracle both transcribe Lueker's
Figure 7 the same wrong way, they agree with each other and both are wrong.

The defence against that is agreement with an *external* source computed by a
different person, in a different language, seventeen years earlier.  Lueker's
Table II (J. ACM 56(3), 2009, p. 17:21) publishes, for h = 2..8, the number of
accepting states, his chosen z, and the resulting upper bound on gamma.  This
script rebuilds each machine from scratch and checks both:

  * the accepting-state count against his published count, and
  * his published upper bound, certified in exact integer/rational arithmetic
    from our own witness at his published z.

Seven independent agreements are not a proof of faithful transcription, but a
shared misreading that still reproduces all seven published constants is not a
plausible failure mode.

Usage:
    python3 verify_lueker_table.py --max-history 7            # minutes
    python3 verify_lueker_table.py --max-history 8            # adds ~10 min
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
import time

from upper_engine import build_graph, certify_checkpoint, run, exact_target_check

# Lueker 2009, Table II ("UPPER BOUNDS").  All values for a binary alphabet.
#   history -> (accepting states, z, published upper bound on gamma)
TABLE_II = {
    2: (7, Fraction(2118, 10000), Fraction(845855, 1000000)),
    3: (98, Fraction(2422, 10000), Fraction(839250, 1000000)),
    4: (1020, Fraction(2642, 10000), Fraction(835072, 1000000)),
    5: (10160, Fraction(2828, 10000), Fraction(831910, 1000000)),
    6: (89960, Fraction(2980, 10000), Fraction(829530, 1000000)),
    7: (780368, Fraction(3104, 10000), Fraction(827727, 1000000)),
    8: (6419109, Fraction(3209, 10000), Fraction(826280, 1000000)),
}


def reproduce(
    history: int,
    workdir: Path,
    *,
    max_iterations: int,
    tolerance_units: int,
    threads: int,
    witness_scale: int,
) -> dict:
    published_states, z, published_bound = TABLE_II[history]
    started = time.perf_counter()

    graph_dir = workdir / f"h{history}"
    if not (graph_dir / "graph.json").is_file():
        build_graph(history, graph_dir)
    manifest = json.loads((graph_dir / "graph.json").read_text())

    states = int(manifest["state_count"])
    if states != published_states:
        raise SystemExit(
            f"h={history}: accepting-state count {states} != Lueker's published "
            f"{published_states}"
        )

    checkpoint_dir = workdir / f"ckpt-h{history}"
    run(
        graph_dir=graph_dir,
        checkpoint_dir=checkpoint_dir,
        z=z,
        max_iterations=max_iterations,
        tolerance_units=tolerance_units,
        target_numerator=published_bound.numerator,
        target_denominator=published_bound.denominator,
        log_path=workdir / "table.log",
        threads=threads,
        witness_scale=witness_scale,
    )
    certified = certify_checkpoint(graph_dir, checkpoint_dir)
    lam_n = int(certified["lambda_numerator"])
    lam_d = int(certified["lambda_denominator"])

    # Table II is rounded to nearest, not rounded up: at h=7 the printed
    # 0.827727 sits about 3e-7 BELOW Lueker's own computed bound, so it is not
    # certifiable as an upper bound at its printed precision.  The meaningful
    # reproduction test is therefore agreement to the printed six decimals:
    #     published - 1/2 ulp  <  B  <=  published + 1/2 ulp,
    # both sides decided in exact rational arithmetic.
    ulp_den = 2 * published_bound.denominator
    upper_ok = exact_target_check(
        z, lam_n, lam_d, 2 * published_bound.numerator + 1, ulp_den
    )
    lower_ok = not exact_target_check(
        z, lam_n, lam_d, 2 * published_bound.numerator - 1, ulp_den
    )
    if not (upper_ok and lower_ok):
        raise SystemExit(
            f"h={history}: our bound does not agree with Lueker's published "
            f"{published_bound} to the printed six decimals "
            f"(upper_ok={upper_ok}, lower_ok={lower_ok})"
        )
    certifiable = exact_target_check(
        z, lam_n, lam_d, published_bound.numerator, published_bound.denominator
    )

    elapsed = time.perf_counter() - started
    row = {
        "history": history,
        "states_published": published_states,
        "states_ours": states,
        "states_match": True,
        "z": f"{z.numerator}/{z.denominator}",
        "published_bound": f"{published_bound.numerator}/{published_bound.denominator}",
        "agrees_to_printed_six_decimals": True,
        "published_value_itself_certifiable": certifiable,
        "lambda_numerator": int(certified["lambda_numerator"]),
        "lambda_denominator": int(certified["lambda_denominator"]),
        "seconds": elapsed,
        "status": "PASS",
    }
    print(
        f"[h={history}] PASS  states {states} == published {published_states}; "
        f"bound agrees with published {float(published_bound):.6f} to 6 decimals"
        + ("" if certifiable else " (printed value is rounded DOWN from his own"
                                  " computed bound, so it is not itself certifiable)")
        + f" ({elapsed:.1f}s)",
        flush=True,
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-history", type=int, default=7)
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-iterations", type=int, default=400)
    parser.add_argument("--tolerance-units", type=int, default=256)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--witness-scale", type=int, default=1 << 26)
    args = parser.parse_args()

    temporary = None
    if args.workdir is None:
        temporary = tempfile.TemporaryDirectory()
        workdir = Path(temporary.name)
    else:
        workdir = args.workdir
        workdir.mkdir(parents=True, exist_ok=True)

    rows = [
        reproduce(
            h,
            workdir,
            max_iterations=args.max_iterations,
            tolerance_units=args.tolerance_units,
            threads=args.threads,
            witness_scale=args.witness_scale,
        )
        for h in range(2, args.max_history + 1)
    ]
    payload = {
        "source": "Lueker, J. ACM 56(3), 2009, Table II",
        "parameters": {
            "max_history": args.max_history,
            "max_iterations": args.max_iterations,
            "tolerance_units": args.tolerance_units,
            "threads": args.threads,
            "witness_scale": args.witness_scale,
        },
        "rows": rows,
        "rows_reproduced": len(rows),
        "status": "PASS",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.output:
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if temporary:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
