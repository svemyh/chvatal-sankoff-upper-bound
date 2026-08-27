# An Improved Upper Bound for the Binary Chvátal–Sankoff Constant

**Result:**  γ₂ ≤ 824443/1000000 = **0.824443**, improving the previous
peer-reviewed and independently certified upper bound 0.826280 (Lueker,
*J. ACM* 2009).

γ₂ is the Chvátal–Sankoff constant: the limit of (expected length of the longest common
subsequence of two uniformly random binary strings of length n) / n. Open since 1975.
The peer-reviewed range before this work was
0.792665992 ≤ γ₂ ≤ 0.826280; the lower endpoint is from the
[ISIT 2025 publication](https://doi.org/10.1109/ISIT63088.2025.11195592).
Qingqing Liu's 2018 dissertation separately reported 0.825101 from a rerun of
Lueker's program with better parameters and computing resources, but did not
publish the parameters, certificate, or replayable computation needed to audit
that number independently. We therefore distinguish that
[dissertation report](https://hdl.handle.net/1853/60772) from the previous
peer-reviewed/certified record. The new 0.824443 certificate improves both
0.826280 (by 0.001837) and the reported 0.825101 (by 0.000658).

The automaton/generating-function method was introduced by
[Dančík and Paterson (1995)](https://doi.org/10.1002/rsa.3240060408); Lueker's
2009 finite-history refinement yields the finite certificate used here. The
machine reads grouped minimal-match pairs and stores suffixes together with LCS
boundary-difference state. The certificate is a vector of positive integers,
one per accepting state of the complete history-10 automaton (400,253,317
states), satisfying `A_z v ≤ λ v` coordinate-wise with z = 3209/10000 and
λ = 1464651560/2³². Checking the certificate requires no trust in how it was
found, while correctness of the automaton remains a separate obligation.

Authors: **Ara** (an autonomous AI software engineer developed at ara.so) and
**Sven Myhre**, `research@ara.so`. Ara selected the target, wrote the builder, the oracle, the
search, and the verifier, and drafted the manuscript; Sven Myhre directed the work, set the
verification standard, independently replayed the verifier, and takes responsibility for the
correctness of the claim. See `paper/` for the manuscript.

## Verify exactly without the 60.8 GB graph

**Deferred h=10 gate:** the verifier is implemented and exhaustively tested through
`h=6`, but the split h=10 state-table assets have not been published and the full
15,209,626,046-transition run has not been performed. No h=10 PASS is claimed. The manifest
marks the table `DEFERRED`, so the default command fails closed instead of
pretending to download or verify unavailable data.

Once those assets are published, the final external command is:

```sh
uv sync --frozen
uv run --frozen python verify_matrix_free.py
```

The code is already wired to automatically download and authenticate only the split 3.2 GB
state table and 1.6 GB final witness once URLs and part hashes are published. A user who
already has the canonical state table can exercise the complete path now with
`--states /path/to/states.u64`; the published witness still downloads
automatically. The verifier builds a derived 2 GiB membership index, resumes after
interruption, checks all transitions and exact integer row inequalities, and writes a small
machine-readable evidence JSON. The projected envelope is 10 GiB free disk, at least 12 GiB
RAM (16 GiB recommended), and a sustained multicore CPU run. See
[`docs/MATRIX_FREE_VERIFICATION.md`](docs/MATRIX_FREE_VERIFICATION.md) for the exact
proof contract, trust boundary, checkpoint behavior, benchmark, and the distinction between
verification and reproduction, including the explicit deferred items.

## Dense replay / reproduce (~90 minutes end to end)

Requirements: `uv` 0.10.2, a Clang or GCC-compatible C11 compiler, at least 80 GiB free
disk, at least 64 GiB RAM, and preferably 128 GiB for witness generation. The recorded
verifier peaked at 40.9 GiB RSS and witness generation at 56.2 GiB, so 32 GiB is not
sufficient. The lock selects CPython 3.11.14, NumPy 1.26.4, Numba 0.59.1, and
llvmlite 0.42.0. Supported generation hosts are macOS and Linux on architectures where
Clang/GCC provide `unsigned __int128`; set `CC` to choose the compiler.

```sh
REPLAY_ROOT=reproduction/shipped-v1.0.0
CANDIDATE_SHA="$(git rev-parse HEAD)"
python3 scripts/preflight_path_a.py \
  --expected-commit "$CANDIDATE_SHA" --output-root "$REPLAY_ROOT"
uv sync --frozen
test ! -e "$REPLAY_ROOT"
mkdir -p "$REPLAY_ROOT/upper_graphs"
sh scripts/fetch_witness.sh "$REPLAY_ROOT/checkpoints"
uv run --frozen python upper_engine.py build-graph --history 8 \
  --graph-dir "$REPLAY_ROOT/upper_graphs/h8"
uv run --frozen python upper_engine.py build-graph --history 10 \
  --graph-dir "$REPLAY_ROOT/upper_graphs/h10"
uv run --frozen python verify_upper.py \
  --graph-root "$REPLAY_ROOT/upper_graphs" \
  --checkpoint-root "$REPLAY_ROOT/checkpoints"

# Optional lineage, calibration, and diagnostic checks:
uv run --frozen python verify_upper.py --with-provenance \
  --graph-root "$REPLAY_ROOT/upper_graphs" \
  --checkpoint-root "$REPLAY_ROOT/checkpoints"
```

This deliberately keeps generated graphs and downloaded arrays out of the tracked
`checkpoints/` metadata directories. `scripts/fetch_witness.sh` authenticates both release
assets before the verifier sees them.

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
historical combined replay, not a promised runtime for the current split verifier; rebuilding
the h=10 machine remains the dominant setup cost.

The default command is deliberately limited to proof-critical checks:

- SHA-256 authentication of the record graph and witness checkpoint;
- strict positivity, declared scale, and successor-index closure;
- the feasibility inequality at every one of the 400,253,317 states (integer arithmetic);
- the final comparison `2 log(2z)/log(lambda) <= 824443/1000000` in exact rationals;
- a read-only assertion that the verifier modified no artifact.

`python3 verify_upper.py --with-provenance` additionally checks the saved certificate JSON,
source PDF when present, machine-sizing record, hash-chained sweep log, exact rescale lineage,
h=8 calibration, and the following diagnostic controls:

- **negative control**: the same witness does *not* prove the next target 0.824442;
- **sharpness control**: the h=8 calibration witness does *not* prove better than Lueker's
  published 0.826280, so the pipeline is not silently optimistic;
- **adversarial control**: a deliberately corrupted witness *is* rejected at the per-state
  test (proving the check can fail);

Those provenance and diagnostic checks increase confidence in how the witness was produced,
but they are not premises of the finite certificate.

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
uv run --frozen python verify_graph_oracle.py exhaustive --max-history 6

# random rows of the actual record machine, recomputed by the oracle
uv run --frozen python verify_graph_oracle.py sample \
    --graph-dir reproduction/shipped-v1.0.0/upper_graphs/h10 \
    --samples 20000 --seed 20260825
```

The exhaustive command also validates the exact start state, unique canonical quotient
representatives, successor closure, reachability, and reference completeness. Results shipped
here: exhaustive agreement for h = 2..6 (1,979,120 transitions at h=6), and
760,000 transitions of the h=10 machine recomputed with zero mismatches
(`h10-oracle-spotcheck.json`). This is strong evidence, not proof: the sample covers a small
fraction of the machine, and a misreading of Figure 7 common to both implementations would
escape both. The h=8 calibration reproducing Lueker's published constant is independent
evidence against that failure mode. The full-h10 command exists but has not been run; no
`h10-oracle-full.json` result has been produced. See
[`docs/FULL_H10_ORACLE.md`](docs/FULL_H10_ORACLE.md) for the future-run contract.

## Bounded continuous integration

GitHub Actions runs the complete 56-test bounded suite, strict Linux C11 and shell checks,
the independent exhaustive graph/oracle contract through h=6, the Lueker Table II
reproduction through h=4, and a twice-repeated manuscript build. It never downloads or
builds the h=10 graph or witness. See [`docs/CI.md`](docs/CI.md) for the exact guarantees
and limits.

## Reproduce from scratch

The deterministic from-scratch path is exercised at bounded histories without touching the
h=10 record:

```sh
uv run --frozen python -m unittest -v test_reproduction.py
```

That test creates two independent h=3 graphs/checkpoint lineages and requires identical
graph and `.npy` hashes, reproduces Lueker Table II through h=4, and checks the Path A
preflight's immutable resource/commit rules. See `REPRODUCE.md` for the fully explicit
bounded commands and the h=10 migration boundary.

## Repository layout

| path | contents |
|---|---|
| `verify_upper.py` | proof-critical verifier, with optional provenance validation |
| `verify_matrix_free.py`, `upper_matrix_free.c` | exact resumable verifier that regenerates transitions without the dense graph |
| `upper_engine.py`, `upper_oracle.py` | deterministic graph builder, power iteration, exact certification/reference model |
| `upper_contract.py` | builder-independent structural and semantic graph contract |
| `upper_graph_builder.c`, `upper_state_builder.c` | C kernels, compiled on demand |
| `upper-h10-certificate.json` | the certificate parameters and hashes |
| `checkpoints/` | checkpoint metadata (+ small h=8 calibration witness; large states fetched) |
| `paper/` | manuscript (LaTeX + PDF) |
| `VERIFICATION.md` | plain-language account of the trust chain and its limits |
| `docs/FULL_H10_ORACLE.md` | unexecuted future full-h10 command and acceptance gate |
| `docs/RELEASE_V1.1.0_GATE.md` | pending v1.1.0 release sequence, Path A evidence contract, and release notes |
| `verify_graph_oracle.py` | independent oracle cross-check of the built automaton (`exhaustive` / `sample` / `full`) |
| `docs/MATRIX_FREE_VERIFICATION.md` | one-command graph-free verification contract and resource envelope |
| `verify_lueker_table.py` | reproduces all seven rows of Lueker's published Table II |
| `lueker-table-ii-reproduction.json` | result of that external agreement check |
| `h10-oracle-spotcheck.json` | result of the h=10 oracle sample check |
| `test_upper_engine.py`, `test_upper_oracle.py`, `test_upper_contract.py`, `test_reproduction.py` | unit, proof-contract, and bounded clean-clone tests |
| `scripts/preflight_path_a.py` | read-only disk, RAM, toolchain, lock, commit, and destination preflight |
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
