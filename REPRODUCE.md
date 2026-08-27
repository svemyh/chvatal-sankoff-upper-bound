# Reproducing γ₂ ≤ 0.824443

There are two distinct reproducibility paths:

1. Replay the shipped h=10 certificate in fresh output directories. This reproduces the
   published claim and does not run power iteration.
2. Generate a new deterministic witness from scratch. This path is tested and hash-stable
   at bounded histories. A new h=10 campaign is intentionally not part of this repository
   update; see the migration boundary below.

## Locked environment and supported platform

Install `uv` 0.10.2, then run:

```sh
uv sync --frozen
uv run --frozen python -VV
uv run --frozen python -c 'import numpy,numba,llvmlite; print(numpy.__version__, numba.__version__, llvmlite.__version__)'
```

`.python-version`, `pyproject.toml`, and `uv.lock` pin CPython 3.11.14, NumPy 1.26.4,
Numba 0.59.1, llvmlite 0.42.0, and uv 0.10.2. `requirements.txt` carries matching exact
fallback pins, but the verified commands use the lock.

Graph generation and exact normalization support macOS and Linux with a Clang or
GCC-compatible C11 compiler that provides `unsigned __int128`. The engine respects `CC`:

```sh
CC=clang uv run --frozen python upper_engine.py --help
```

Graph `uint64` states and `uint32` successors are serialized explicitly little-endian and
their manifests are rejected unless they declare `<u8` and `<u4`. The unused experimental
matrix-free h=11 state builder remains little-endian-host-only and fails explicitly on any
other host.

## Path A — replay the shipped certificate (~90 minutes)

This needs at least 80 GB free disk and 64 GiB RAM. The verifier's recorded peak was about
41 GiB RSS. The h=10 graph is about 60 GB; the two downloaded arrays total about 3 GB.

```sh
uv sync --frozen
REPLAY_ROOT=reproduction/shipped-v1.0.0
test ! -e "$REPLAY_ROOT"
mkdir -p "$REPLAY_ROOT/upper_graphs"
sh scripts/fetch_witness.sh "$REPLAY_ROOT/checkpoints"

uv run --frozen python upper_engine.py build-graph \
  --history 8 \
  --graph-dir "$REPLAY_ROOT/upper_graphs/h8"
uv run --frozen python upper_engine.py build-graph \
  --history 10 \
  --graph-dir "$REPLAY_ROOT/upper_graphs/h10"

uv run --frozen python verify_upper.py \
  --graph-root "$REPLAY_ROOT/upper_graphs" \
  --checkpoint-root "$REPLAY_ROOT/checkpoints"
```

The final command must print JSON status `PASS` and:

```text
PASS: exact feasible witness proves gamma_2 <= 0.824443 < 0.826280
```

The fresh checkpoint root is populated with authenticated copies of the tracked h=8
calibration and h=10 metadata plus the two authenticated release arrays. Nothing relies on
the deliberately absent h=10 arrays under the tracked `checkpoints/` paths.

## Path B — deterministic bounded generation from scratch

This complete h=4 recipe uses a fresh output directory and makes the target, scale,
tolerance, iteration limit, and thread count explicit:

```sh
uv sync --frozen
BOUNDED_ROOT=reproduction/from-scratch-h4
test ! -e "$BOUNDED_ROOT"
mkdir -p "$BOUNDED_ROOT/logs"

uv run --frozen python upper_engine.py build-graph \
  --history 4 \
  --graph-dir "$BOUNDED_ROOT/graphs/h4"
uv run --frozen python upper_engine.py run \
  --graph-dir "$BOUNDED_ROOT/graphs/h4" \
  --checkpoint-dir "$BOUNDED_ROOT/checkpoints/h4" \
  --z-numerator 2642 \
  --z-denominator 10000 \
  --target-numerator 835072 \
  --target-denominator 1000000 \
  --witness-scale 67108864 \
  --tolerance-units 256 \
  --max-iterations 400 \
  --threads 2 \
  --log "$BOUNDED_ROOT/logs/h4.log"
uv run --frozen python upper_engine.py certify \
  --graph-dir "$BOUNDED_ROOT/graphs/h4" \
  --checkpoint-dir "$BOUNDED_ROOT/checkpoints/h4" \
  --output "$BOUNDED_ROOT/h4-certificate.json"
```

The certificate must report `status: PASS`. The automated clean-clone smoke test repeats a
fresh h=3 generation twice and requires byte-identical graph and witness hashes. It also
reproduces Table II through h=4:

```sh
uv run --frozen python -m unittest -v test_reproduction.py

TABLE_ROOT=reproduction/lueker-table-h4
test ! -e "$TABLE_ROOT"
mkdir -p "$TABLE_ROOT"
uv run --frozen python verify_lueker_table.py \
  --max-history 4 \
  --max-iterations 400 \
  --tolerance-units 256 \
  --witness-scale 67108864 \
  --threads 2 \
  --workdir "$TABLE_ROOT/work" \
  --output "$TABLE_ROOT/result.json"
```

## h=10 deterministic migration boundary

The published h=10 witness remains valid and Path A still verifies it exactly. Its original
power-iteration lineage used binary floating-point only to normalize each proposed witness;
the final proof scan was always integer-exact. The current engine replaces that proposal
step with

```text
V_next[i] = clamp(floor(raw[i] * witness_scale / raw_max), 1, witness_scale)
```

computed by an overflow-safe unsigned-128-bit C kernel. Consequently, new checkpoints are
tagged `upper-fixed-v2-exact-normalization` and cannot resume the historical v1 lineage.
Even a one-unit proposal difference changes all later checkpoint hashes.

A new h=10 run would use the historical schedule below, with every parameter explicit, but
its convergence iteration and hashes must be treated as new results until the expensive run
is actually performed:

```sh
H10_ROOT=reproduction/new-deterministic-h10
test ! -e "$H10_ROOT"
mkdir -p "$H10_ROOT/logs"

uv run --frozen python upper_engine.py build-graph \
  --history 8 --graph-dir "$H10_ROOT/graphs/h8"
uv run --frozen python upper_engine.py run \
  --graph-dir "$H10_ROOT/graphs/h8" \
  --checkpoint-dir "$H10_ROOT/checkpoints/calibration-h8" \
  --z-numerator 3209 --z-denominator 10000 \
  --target-numerator 826280 --target-denominator 1000000 \
  --witness-scale 67108864 --tolerance-units 2048 \
  --max-iterations 203 --threads 18 \
  --log "$H10_ROOT/logs/h8.log"
uv run --frozen python upper_engine.py certify \
  --graph-dir "$H10_ROOT/graphs/h8" \
  --checkpoint-dir "$H10_ROOT/checkpoints/calibration-h8" \
  --output "$H10_ROOT/h8-certificate.json"

uv run --frozen python upper_engine.py build-graph \
  --history 10 --graph-dir "$H10_ROOT/graphs/h10"
uv run --frozen python upper_engine.py run \
  --graph-dir "$H10_ROOT/graphs/h10" \
  --checkpoint-dir "$H10_ROOT/checkpoints/h10-q26" \
  --z-numerator 3209 --z-denominator 10000 \
  --target-numerator 824443 --target-denominator 1000000 \
  --witness-scale 67108864 --tolerance-units 2048 \
  --max-iterations 100 --threads 18 \
  --log "$H10_ROOT/logs/h10.log"
uv run --frozen python upper_engine.py rescale-checkpoint \
  --graph-dir "$H10_ROOT/graphs/h10" \
  --source-dir "$H10_ROOT/checkpoints/h10-q26" \
  --target-dir "$H10_ROOT/checkpoints/h10-q31" \
  --new-witness-scale 2147483648
uv run --frozen python upper_engine.py run \
  --graph-dir "$H10_ROOT/graphs/h10" \
  --checkpoint-dir "$H10_ROOT/checkpoints/h10-q31" \
  --z-numerator 3209 --z-denominator 10000 \
  --target-numerator 824443 --target-denominator 1000000 \
  --witness-scale 2147483648 --tolerance-units 2048 \
  --max-iterations 113 --threads 18 \
  --log "$H10_ROOT/logs/h10.log"
```

Do not feed this new lineage to the shipped-record verifier. Certify it separately only
after it has actually converged. A full deterministic h=10 campaign is intentionally
deferred here; it was not run, downloaded, or regenerated as part of this repair. Allow at
least 80 GB free disk and prefer 96 GiB RAM for such a campaign; the historical run peaked
at 56.2 GiB RSS.

## Unit and bounded integration tests

```sh
uv run --frozen python -m unittest -v \
  test_upper_engine.py test_upper_oracle.py test_reproduction.py
```

The suite covers the exact normalizer over uint64/uint32 boundary values, the verifier-grade
ceiling overflow preflight, overflow-safe ratio scanning, explicit little-endian graph bytes,
restart/rescale behavior, exhaustive oracle agreement through h=4, two independent
byte-identical bounded generations, and Lueker Table II through h=4.
