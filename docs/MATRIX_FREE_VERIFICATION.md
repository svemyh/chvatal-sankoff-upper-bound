# Exact matrix-free h=10 verification

The matrix-free verifier checks the published `gamma_2 <= 0.824443` certificate without
building, downloading, or storing the 60.8 GB transition table and without rerunning power
iteration. It needs only the canonical state table and the final positive integer witness.

## Current status: implementation complete, h=10 execution deferred

The implementation and bounded validation are complete, including exhaustive transition
agreement through `h=6`. The canonical h=10 state table has a previously recorded
size and SHA-256, but its split download assets have **not** been published in this change.
The full 400,253,317-row / 15,209,626,046-transition matrix-free scan has also **not** been
run. Accordingly:

- this repository does not claim a completed matrix-free h=10 PASS;
- `matrix-free-h10-artifacts.json` marks the state table
  `availability: DEFERRED` and contains no invented URLs or part hashes;
- the default command exits nonzero with an explicit deferred-publication error; and
- no release or large artifact is created by this work.

Publishing the split state table, filling its authenticated part manifest, and executing the
full scan are the remaining external-data/runtime gate.

## Final one-command contract

After installing the pinned `uv` 0.10.2 and a Clang/GCC-compatible C11 compiler:

```sh
uv sync --frozen
uv run --frozen python verify_matrix_free.py
```

After state publication, the second line is the complete exact-verification command. The
code will automatically download and SHA-256-authenticate the split state-table artifact and
final witness from pinned URLs, assemble the state table, compile the independent C verifier,
create a derived keyless membership index, and scan the certificate. Interrupted downloads
resume on the same command. A certifying scan does not resume across invocations: it starts
at row zero because a user-writable progress file cannot prove earlier computation occurred.

Until then, a holder of the canonical table can run the same path without bypassing
authentication:

```sh
uv run --frozen python verify_matrix_free.py \
  --states /absolute/path/to/upper-h10-states.u64
```

The supplied file must still be exactly 3,202,026,536 bytes with SHA-256
`defc127da935708620977efddda218378322d9d23921ac3453c9f7a56ff5f59b`.

By default, downloads, the derived index, current-invocation progress, and evidence are
placed in `matrix-free-h10-verification/`. Use `--work-dir PATH` to put them elsewhere,
`--threads N` to set CPU parallelism, or `--states PATH --witness PATH` to use
local copies. Local overrides are still required to match the published sizes and hashes.

Success writes `verification-evidence.json` and ends with:

```text
PASS: exact matrix-free verification proves gamma_2 <= 0.824443
```

Any missing state, malformed artifact, hash mismatch, duplicate/noncanonical state, zero or
overscale witness entry, transition error, absent successor, integer overflow, row
inequality failure, native-binary change, or exact-bound failure exits nonzero and cannot
emit `status: PASS`.

## What is checked

The verifier performs these proof-critical steps:

1. Hashes the 3,202,026,536-byte little-endian state table and the NumPy witness and compares
   them with repository-pinned SHA-256 values. The NumPy header is parsed with the frozen
   NumPy version and must describe exactly 400,253,317 little-endian `uint32` entries
   with no trailing data.
2. Freshly compiles `upper_matrix_free.c` with strict flags into a private directory and
   binds every native execution to the digest of those exact output bytes. A preexisting
   source-hash-named executable is never used.
3. Rebuilds a 2 GiB keyless open-addressing index on every certifying invocation. During
   insertion it rejects duplicate or noncanonical quotient representatives and confirms the
   canonical initial state
   `(x,y,dx,dy)=(0,0,2^10-1,2^10-1)` is present.
4. For every supplied state and all 38 `(character,padding)` labels, evaluates
   Lueker's transition recurrence, its rejecting backtrack, and simultaneous-complement
   quotient. Every accepted successor must be found in the authenticated state set. Thus a
   set that contains the initial state and is closed under the transition relation contains
   every reachable accepting state; harmless extra closed states do not weaken the proof.
5. Recomputes the upward-rounded `2^32` fixed-point weights from
   `z=3209/10000`, checks every witness entry is positive, and accumulates every row
   in `unsigned __int128`. It explicitly rejects a row above `uint64`,
   then checks `S_i <= 1464651560 * V_i` with a 128-bit product.
6. Proves the final normalization without floating point by the direct integer comparison
   `(2z)^2,000,000 >= lambda^824,443`, which is equivalent to
   `2 log(2z)/log(lambda) <= 824443/1000000` because both bases lie in `(0,1)`.

The evidence JSON records input and code hashes, parameters, accepted/rejected transition
counts, exact extrema, the bound decision, runtime, peak scan RSS, platform, compiler, and
an in-memory chain over fresh current-invocation chunk results. That chain is provenance, not
authentication. No chunk summary is read from disk or allowed to contribute to `PASS`.
The derived membership index is not a trusted cache: it is rebuilt after artifact
authentication, and every nonzero lookup entry is dereferenced back into the authenticated
state table before it can establish membership. Later index damage can therefore cause
rejection, not false membership.

## Independence and trust boundary

`upper_matrix_free.c` neither includes nor calls the production graph builder. It
uses its own zero-indexed dynamic program and boundary reconstruction rather than consuming
`transitions.u32`. The bounded suite compares every transition byte produced by
this oracle with the production builder for `h=2..6`; the existing pure-Python
oracle separately checks the mathematical transcription at those histories. The recorded
h=6 benchmark covers all 1,979,120 labels and reports byte-identical outputs.

The trust boundary still includes this repository source, the pinned Python/NumPy runtime,
the selected C compiler, C runtime, operating system, and hardware. It excludes preexisting
native binaries, index metadata, scan-progress JSON, the production graph builder, and the
witness search.

This remains executable mathematics, not a proof-assistant formalization. A shared
misreading of Lueker's specification could affect independent implementations. Agreement
with Lueker's seven published Table II rows is the external defense against that risk, and
Lueker's theorem itself remains assumed.

## Resources and restart behavior

Projected persistent storage after setup is:

| item | bytes |
|---|---:|
| authenticated states | 3,202,026,536 |
| authenticated witness | 1,601,013,396 |
| derived membership index | 2,147,483,648 |
| total retained | 6,950,523,580 |

Assembly temporarily needs at most one additional state part plus a 1 GiB safety margin, so
the verifier preflights roughly 9 GB free and 10 GiB free is the practical minimum. The
three large inputs are memory-mapped; 12 GiB RAM is the conservative minimum and 16 GiB or
more is recommended. The scan regenerates 15,209,626,046 transitions and is CPU-bound.
The checked-in h=6 benchmark is a scale sanity check, not a linear h=10 runtime promise;
large-table random lookup and the higher-history dynamic program are materially more
expensive.

These are design/preflight figures, not measurements from a completed h=10 matrix-free run.
The scan is divided into contiguous 10,000,000-row chunks by default. Each completed chunk
is atomically reflected in a progress JSON so an operator can observe the current process.
That file is never read for proof credit. If the process stops, exact certification restarts
at row zero, freshly compiles the kernel, rebuilds the index, and rescans every row. This is
intentional: a self-hashed writable checkpoint proves byte continuity, not that computation
occurred. The artifact downloads themselves remain resumable.

## Verify versus reproduce

Verification authenticates an already published state set and witness, regenerates every
transition, proves closure, checks all inequalities, and certifies the final rational bound.
It does not trust or need the saved transition graph and does not trust the witness search.

Reproduction is the much larger authoring workflow: rediscover the canonical state set,
optionally materialize the dense graph, rerun power iteration, and produce a new witness.
That path remains in `REPRODUCE.md`. It needs substantially more disk/RAM and
hours of search; it is not a prerequisite for checking the theorem.

## Bounded validation and benchmark

Run the focused tests with:

```sh
uv run --frozen python -m unittest -v test_matrix_free.py
```

They exhaustively compare the independent matrix-free transition oracle through `h=6`
and exercise corruption, overflow, closure, rejection, positivity, exact-bound, and
adversarial forged-checkpoint, planted-binary, and forged-index-cache paths.
`matrix-free-h6-benchmark.json` is a reproducible four-thread
macOS measurement; make a fresh measurement with:

```sh
uv run --frozen python scripts/benchmark_matrix_free.py --history 6 --threads 4
```

The bounded benchmark must not be extrapolated into a claimed h=10 runtime. The honest
remaining requirements are publication/download of the 3.2 GB state table, about 7 GB
retained verifier data, and one full sustained scan whose runtime and peak RSS will only be
known after it is actually executed.
