# Exact `h=10` upper run

Date: 2026-08-24 UTC  
Scope: tracked upper task 004; convergence run and independent exact certificate

## Outcome

The largest safe history selected by the 20 GiB reserve rule, `h=10`,
converged after 113 complete sweeps.  The final positive integer witness passes
all 400,253,317 componentwise inequalities in an independent exact scan.  Its
certificate is

```text
z                    = 3209 / 10000
Lambda               = 1464651560
weight denominator   = 2^32 = 4294967296
lambda               = Lambda / 2^32
state SHA-256         = e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436
graph identity        = e4db7c10b0b55060c3a9beff010583a593b4c24bc13600ecb219b933a2806f7a
```

The exact logarithmic comparison passes for `824443/1000000` and fails for
`824442/1000000`.  Therefore this witness supports the rigorous six-decimal
statement

```text
gamma_2 <= 0.824443 < 0.826280.
```

The direct floating rendering
`2*log(2z)/log(Lambda/2^32) = 0.824442457097411...` is descriptive only; it
does not participate in either feasibility or the record comparison.  The
final disposition and standalone replay belong to task 005.

## Exact certificate

For every transition column `j`, the engine stores

```text
W_j = ceil(2^32 * a_j),
```

where `a_j` is Lueker's exact rational grouped match-pair weight.  For every
state `i`, the full scan computes the uint64 integer

```text
S_i = sum_j W_j * V[successor(i,j)]
```

over non-rejecting transitions and verifies

```text
S_i <= Lambda * V_i.
```

Since every `W_j/2^32 >= a_j`, this proves the original componentwise
inequality `A_z V <= (Lambda/2^32) V`.  The final scan found failing state `-1`
(none), maximum actual row sum `3,145,313,150,651,095,756`, and positive
witness range `9,834,007..2,147,483,648`.

The stopping diagnostic was fixed before the run at

```text
max_i ceil(S_i/V_i) - min_i floor(S_i/V_i) <= 2048.
```

Iteration 113 attained `1464651560 - 1464649541 = 2019`, or
`2019/2^32 = 4.700850695371628e-7`.  Feasibility and the target comparison were
also required; the width condition alone is not a certificate.

The normalization theorem is checked without floating logarithms.  For a
candidate rational `p/q`, with `0 < 2z,lambda < 1`,

```text
2 log(2z) / log(lambda) <= p/q
iff (2z)^(2q) >= lambda^p.
```

`exact_target_check` decides this through rigorously bounded rational log
series.  It returned true for `p/q=824443/1000000` and false for
`824442/1000000`.

## Rounding and overflow budget

| quantity | rigorous treatment |
|---|---|
| automaton states/transitions | exact integer files, SHA-256 authenticated |
| exact grouped weights `a_j` | `fractions.Fraction` |
| stored weights | rounded upward by `ceil(2^32*a_j)` |
| maximum one-column upward error | `19643428001176716801879 / 10^32`, about `1.96435e-10` |
| maximum sum of all 38 upward errors | `26123701686 / 5696703692800000000`, about `4.58576e-9` |
| witness storage | exact positive uint32 integers; 0 stored-state error units |
| row sums | exact uint64 integer additions/products; 0 integer-sum error units |
| feasibility comparison | exact integer comparison; 0 comparison error units |
| normalization comparison | rigorous rational intervals; no binary float verdict |

Upward coefficient rounding makes the stored matrix entrywise larger, so it
can only weaken the resulting upper bound; no subtraction of a floating error
term is needed.  Floating point is used only to propose the next witness during
optimization.  The saved integers are treated as a new exact witness in every
certificate scan.

The worst-case preflight row sum is
`3,694,837,743,432,499,200`, below `2^64-1` by
`14,751,906,330,277,052,415`.  The preflight and the measured final raw maximum
both exclude uint64 overflow.

## Restart chain and precision migration

Sweeps 1--100 used witness scale `Q=2^26`.  The target first passed at sweep
18, but the exact ratio width plateaued at 10,145 units, above the unchanged
2,048-unit stopping gate.  The iteration-100 witness was therefore multiplied
exactly by 32 into a new transactional checkpoint with `Q=2^31`; uniform
integer scaling preserves every row ratio and feasibility inequality.

```text
iteration-100 parent hash   6501dd40a1894cfc4c8cd6cf2023078693ebe16a3e3158130e87d23f62afb6ba
rescaled child hash         bcba07e3635ab2a0be4520d6b737366eaa55006dc4b42d76fc9c6690c0a3506f
rescale factor              32
high-precision sweeps       101..113
```

The migration test checks exact elementwise multiplication and restart.  An
additional read-only audit reconstructed the complete child `.npy` byte stream
from the saved parent and reproduced `bcba...3506f`; that hash is also the
logged source of sweep 101.  The final log audit found exactly 113 distinct
sweep IDs and exactly one entry for every integer iteration 1--113.  All 113
entries are feasible.  Parent hashes link 1--100 and 101--113; the explicit
rescale record links the two segments.

## Runtime, memory, and transition range

The two run segments plus the exact rescale took 10,265.32 seconds
(2.85148 hours) wall clock: 8,941.65 seconds for the original segment, 28.91
seconds to authenticate/rescale, and 1,294.76 seconds for the high-precision
segment.  The final independent replay took 56.51 seconds, including complete
graph and state hashing plus a 23.2453-second matrix application.

Across 113 completed sweeps:

| phase | minimum s | median s | maximum s | total s |
|---|---:|---:|---:|---:|
| optimize/application + normalization | 28.3875 | 37.8729 | 85.3702 | 4,947.0032 |
| independent-in-sweep application/certificate | 29.4125 | 38.7644 | 94.8450 | 4,845.1039 |
| atomic checkpoint write/hash | 0.7481 | 0.8989 | 3.4312 | 121.3695 |

The maximum timed-run RSS was 60,317,810,688 bytes (56.1753 GiB), with zero
swaps.  The independent replay peaked at 43,922,456,576 bytes (40.9060 GiB).

The authenticated transition array has shape `400253317 x 38`, or
15,209,626,046 entries.  A complete read-only range scan found 6,574,257,580
valid successors spanning exactly `0..400253316` and 8,635,368,466 reject
sentinels equal to `4294967295`.  No successor lies outside the state range.

## Reproduction evidence

The independent result is saved in `upper-h10-certificate.json` (SHA-256
`523fb826c7c7e18310cb1625a04d375017ed228bef911063634022560ff012ff`).
The decisive scan was:

```text
../.venv/bin/python upper_engine.py certify \
  --graph-dir upper_graphs/h10 \
  --checkpoint-dir checkpoints/upper-h10-q31 \
  --output upper-h10-certificate.json
```

It returned `status: PASS`, `feasible: true`, `target_pass: true`,
`failing_state: -1`, and all three integer feasibility error fields equal to
zero.  `LOG.md` contains the 113 UTC `upper-sweep` records, the exact rescale
record, and the final run milestone.

