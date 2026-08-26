# Reproducing γ₂ ≤ 0.824443

Two paths. Both end with `python3 verify_upper.py` printing
`PASS: exact feasible witness proves gamma_2 <= 0.824443 < 0.826280`.

Machine used for the original run: 18-core Apple Silicon desktop, 128 GB RAM.
The record run (113 power-iteration sweeps at h=10 plus the rescale) took
10,265 s (2.85 h) and peaked at 56.2 GiB RSS. Graph builds: h=8 in minutes,
h=10 in roughly an hour and ~60 GB of disk.

## Path A — verify the shipped certificate (~90 min wall, mostly graph build)

```sh
pip install -r requirements.txt
sh scripts/fetch_witness.sh
python3 upper_engine.py build-graph --history 8  --graph-dir upper_graphs/h8
python3 upper_engine.py build-graph --history 10 --graph-dir upper_graphs/h10
python3 verify_upper.py
```

The graphs are deterministic; the verifier authenticates them against pinned
SHA-256 identities (h=8: `4c2514a4…`, h=10: `e4db7c10…`) before using them, so
a corrupted or divergent build fails loudly.

## Path B — re-derive the witness from scratch (no downloads; ~4 h)

```sh
pip install -r requirements.txt
python3 upper_engine.py build-graph --history 8  --graph-dir upper_graphs/h8
python3 upper_engine.py build-graph --history 10 --graph-dir upper_graphs/h10

# calibration gate: reproduce Lueker's 0.826280 at h=8
python3 upper_engine.py run --graph-dir upper_graphs/h8 \
  --checkpoint-dir checkpoints/upper-calibration-h8 \
  --z-numerator 3209 --z-denominator 10000

# the record run at h=10 (witness scale 2^26)
python3 upper_engine.py run --graph-dir upper_graphs/h10 \
  --checkpoint-dir checkpoints/upper-h10 \
  --z-numerator 3209 --z-denominator 10000

# exact rescale of the witness to scale 2^31 (this is the certified lineage)
python3 upper_engine.py rescale-checkpoint --graph-dir upper_graphs/h10 \
  --source-dir checkpoints/upper-h10 --target-dir checkpoints/upper-h10-q31 \
  --new-witness-scale 2147483648

# continue iteration at the finer scale until the certificate passes
python3 upper_engine.py run --graph-dir upper_graphs/h10 \
  --checkpoint-dir checkpoints/upper-h10-q31 \
  --z-numerator 3209 --z-denominator 10000 \
  --target-numerator 824443 --target-denominator 1000000

# exact certification and the standalone verifier
python3 upper_engine.py certify --graph-dir upper_graphs/h10 \
  --checkpoint-dir checkpoints/upper-h10-q31 --output upper-h10-certificate.json
python3 verify_upper.py
```

Note: path B regenerates the witness; power iteration is deterministic given
the graph and parameters, and the shipped checkpoints' SHA-256 values
(`docs/UPPER_H10_RESULT.md`) pin the exact states of record.

## Expected key values

| quantity | value |
|---|---|
| states (h=10) | 400,253,317 |
| z | 3209/10000 |
| λ (numerator / 2³²) | 1,464,651,560 |
| final iteration | 113 |
| certified bound | 824443/1000000 |
| negative control | 824442/1000000 must NOT pass |
| calibration (h=8) | reproduces 0.826280 (Lueker 2009) |

## Provenance docs

`docs/` contains the campaign's own reports: the source-exact extraction of
Lueker's theorem (`UPPER_FORMULATION.md`), the calibration report
(`UPPER_CALIBRATION.md`), the record-run report with timings, hashes, and the
rescale lineage (`UPPER_H10_RESULT.md`), and the result summary
(`RESULTS_UPPER.md`).

## Validating the automaton against the oracle

```sh
python3 verify_graph_oracle.py exhaustive --max-history 6
python3 verify_graph_oracle.py sample --graph-dir upper_graphs/h10 \
    --samples 20000 --seed 20260825 --output h10-oracle-spotcheck.json
```

Expected: `PASS` for every history 2..6 (exhaustive) and zero mismatches over 760,000
sampled h=10 transitions. Raising `--samples` costs about 13 ms per row; the fixed cost is
building a sorted index over the 400M states (~4 min, ~7 GB RAM).

## Unit tests

```sh
python3 -m unittest test_upper_engine test_upper_oracle
```

Expected: 9 engine tests and 8 oracle tests, all passing. (The h=11 matrix-free experiments
from the wider campaign are not part of this artifact; tests depending on them were removed
rather than shipped half-built.)
