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

The mathematical search, the computations, and the write-up were carried out by AI agent
systems directed and verified by a human operator. See `paper/` for the manuscript.

## Verify (fast path, ~1 hour total)

Requirements: Python 3.11+, `numpy`, `numba`, a C compiler (`clang` or `cc`), ~65 GB free
disk, 32 GB+ RAM recommended.

```sh
pip install -r requirements.txt
sh scripts/fetch_witness.sh          # downloads the 3.0 GB witness (release assets) + SHA-256 check
python3 upper_engine.py build-graph --history 8  --graph-dir upper_graphs/h8    # ~minutes
python3 upper_engine.py build-graph --history 10 --graph-dir upper_graphs/h10   # ~1 h, ~60 GB
python3 verify_upper.py              # ~72 s on an 18-core machine
```

`verify_upper.py` ends with JSON `"status": "PASS"` and the line

```
PASS: exact feasible witness proves gamma_2 <= 0.824443 < 0.826280
```

What it checks:
- SHA-256 authentication of the graphs, the witness checkpoints, and the certificate;
- the feasibility inequality at every one of the 400,253,317 states, in integer arithmetic;
- the final comparison `2 log(2z)/log λ ≤ 824443/1000000` via exact rational enclosures
  (no floating-point value decides any inequality);
- a negative control: the same witness does **not** prove the next smaller six-decimal
  target 0.824442;
- the calibration gate: the same pipeline at history 8 reproduces Lueker's published
  0.826280;
- rejection of a deliberately tampered certificate.

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
| `test_upper_engine.py`, `test_upper_oracle.py` | unit tests for the engine and oracle |
| `sources/papers/lueker-2009.pdf` | frozen primary source, SHA-pinned by the verifier |

## Citation

```bibtex
@misc{ara2026chvatalsankoff,
  title  = {An Improved Upper Bound for the Binary Chv\'atal--Sankoff Constant},
  author = {Ara},
  year   = {2026},
  note   = {gamma_2 <= 0.824443; replayable certificate at this repository}
}
```
