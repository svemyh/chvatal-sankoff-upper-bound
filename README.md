# An Improved Upper Bound for the Binary Chvátal–Sankoff Constant

**Result:**  γ₂ ≤ 824443/1000000 = **0.824443**, improving the previous best upper bound
0.826280 (Lueker, *J. ACM* 2009), which had stood for 17 years.

γ₂ is the Chvátal–Sankoff constant: the limit of (expected length of the longest common
subsequence of two uniformly random binary strings of length n) / n. Open since 1975.
Known range before this work: 0.792665992 ≤ γ₂ ≤ 0.826280.

The proof is a finite certificate in the sense of Lueker (2009), eq. (41) / Theorem 3.3:
a vector of positive integers, one per state of the complete history-10 automaton
(400,253,317 states), satisfying `A_z v ≤ λ v` coordinate-wise with z = 3209/10000 and
λ = 1464651560/2³². Checking the certificate requires no trust in how it was found.

Authors: **Ara** (an autonomous AI software engineer developed at ara.so) and
**Sven Myhre**, `research@ara.so`. Ara selected the target, wrote the builder, the oracle, the
search, and the verifier, and drafted the manuscript; Sven Myhre directed the work, set the
verification standard, independently replayed the verifier, and takes responsibility for the
correctness of the claim. See `paper/` for the manuscript.

## Verify (~90 minutes end to end)

Requirements: Python 3.11+, `numpy`, `numba`, a C compiler (`clang` or `cc`), ~65 GB free
disk, 32 GB+ RAM recommended.

```sh
pip install -r requirements.txt
sh scripts/fetch_witness.sh          # downloads the 3.0 GB witness (release assets) + SHA-256 check
python3 upper_engine.py build-graph --history 8  --graph-dir upper_graphs/h8    # ~1 min
python3 upper_engine.py build-graph --history 10 --graph-dir upper_graphs/h10   # ~1 h, ~60 GB
python3 verify_upper.py              # ~75 s
```

`verify_upper.py` ends with JSON `"status": "PASS"` and the line

```
PASS: exact feasible witness proves gamma_2 <= 0.824443 < 0.826280
```

**Honest description of the verifier.** It uses NumPy and Numba to apply the operator over
400 million states; it is *not* a pure standard-library program. But every inequality that
*decides* the claim is evaluated in Python integers and `Fraction`s: the per-state test is
an integer comparison `S_i <= Lambda * V_i` against the `Lambda` pinned in the script, and
the final bound comparison uses exact rational log enclosures with explicit remainder
bounds. No floating-point value decides anything. The commonly quoted "72 seconds" is the
final scan only; the hour before it is rebuilding the machines.

What it checks:
- SHA-256 authentication of graphs, witness checkpoints, and the certificate (plus the
  primary-source PDF if you supply your own copy; it is ACM-copyrighted and not
  redistributed here, see `scripts/fetch_source_paper.sh`);
- the feasibility inequality at every one of the 400,253,317 states (integer arithmetic);
- the final comparison `2 log(2z)/log(lambda) <= 824443/1000000` in exact rationals;
- the hash-chained per-sweep log covering all 113 iterations and the exact rescale;
- **negative control**: the same witness does *not* prove the next target 0.824442;
- **sharpness control**: the h=8 calibration witness does *not* prove better than Lueker's
  published 0.826280, so the pipeline is not silently optimistic;
- **adversarial control**: a deliberately corrupted witness *is* rejected at the per-state
  test (proving the check can fail);
- a read-only assertion that the verifier modified no artifact.

## How to know the number is right

See **[VERIFICATION.md](VERIFICATION.md)** for the whole trust chain in plain language:
what is machine-checked, what is corroborated by an external source, and what is not
proven. Two headline items are summarised below.

## Validate the machine itself (recommended)

The certificate quantifies over the h=10 automaton, and hashing authenticates *bytes*, not
*semantics*. The soundness-critical direction is a spurious rejection: rejected columns are
dropped from the row sum, so a legitimate transition wrongly marked rejecting would
understate the operator and make the bound look better than it is. `verify_graph_oracle.py`
cross-checks the C builder against an independent pure-Python transcription of Lueker's
Figure 7 (`upper_oracle.py`):

```sh
# every state, every column, for small machines
python3 verify_graph_oracle.py exhaustive --max-history 6

# random rows of the actual record machine, recomputed by the oracle
python3 verify_graph_oracle.py sample --graph-dir upper_graphs/h10 \
    --samples 20000 --seed 20260825
```

Results shipped here: exhaustive agreement for h = 2..6 (1,979,120 transitions at h=6), and
760,000 transitions of the h=10 machine recomputed with zero mismatches
(`h10-oracle-spotcheck.json`). This is strong evidence, not proof: the sample covers a small
fraction of the machine, and a misreading of Figure 7 common to both implementations would
escape both. The h=8 calibration reproducing Lueker's published constant is independent
evidence against that failure mode.

## Reproduce from scratch (no downloaded witness)

The witness itself is re-derivable by power iteration (hours on an 18-core desktop):

```sh
python3 upper_engine.py build-graph --history 10 --graph-dir upper_graphs/h10
python3 upper_engine.py run --graph-dir upper_graphs/h10 \
    --checkpoint-dir checkpoints/upper-h10 --z-numerator 3209 --z-denominator 10000
python3 upper_engine.py rescale-checkpoint   # see REPRODUCE.md for exact arguments
python3 verify_upper.py
```

See `REPRODUCE.md` for the full command log, machine details, and expected hashes.

## Repository layout

| path | contents |
|---|---|
| `verify_upper.py` | standalone verifier (the artifact of record; do not modify) |
| `upper_engine.py`, `upper_oracle.py` | graph builder, power iteration, exact certification |
| `upper_graph_builder.c`, `upper_state_builder.c` | C kernels, compiled on demand |
| `upper-h10-certificate.json` | the certificate parameters and hashes |
| `checkpoints/` | checkpoint metadata (+ small h=8 calibration witness; large states fetched) |
| `paper/` | manuscript (LaTeX + PDF) |
| `VERIFICATION.md` | plain-language account of the trust chain and its limits |
| `verify_graph_oracle.py` | independent oracle cross-check of the built automaton (`exhaustive` / `sample` / `full`) |
| `verify_lueker_table.py` | reproduces all seven rows of Lueker's published Table II |
| `lueker-table-ii-reproduction.json` | result of that external agreement check |
| `h10-oracle-spotcheck.json` | result of the h=10 oracle sample check |
| `test_upper_engine.py`, `test_upper_oracle.py` | unit tests (`python3 -m unittest test_upper_engine test_upper_oracle`) |
| `scripts/fetch_source_paper.sh` | authenticates your own copy of Lueker 2009 (ACM-copyrighted, not redistributed) |

## Citation

```bibtex
@misc{ara2026chvatalsankoff,
  title  = {An Improved Upper Bound for the Binary Chv\'atal--Sankoff Constant},
  author = {{Ara} and Myhre, Sven},
  year   = {2026},
  note   = {gamma_2 <= 0.824443; replayable certificate at this repository}
}
```
