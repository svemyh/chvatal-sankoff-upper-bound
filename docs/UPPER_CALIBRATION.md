# Exact reproduction of Lueker's `0.826280` upper bound

Date: 2026-08-24 UTC  
Scope: tracked upper task 002  
Status: **calibration gate passed in exact arithmetic**

## Certified result

The locally generated `h=8` automaton has exactly the 6,419,109 accepting
states reported in Lueker's Table II.  At the published parameter

```text
z = 0.3209 = 3209/10000
```

the saved positive integer witness at iteration 203 satisfies every component
of Lueker's equation (41).  The exact conservative eigenvalue bound is

```text
lambda = 1,468,159,907 / 4,294,967,296
       = 0.34183261613361537456512451171875.
```

The exact normalization check proves

```text
(2z)^2,000,000 >= lambda^826,280,
```

which is algebraically equivalent to

```text
2 log(2z) / log(lambda) <= 826280/1000000.
```

Thus Lueker's published `gamma_2 <= 0.826280` is reproduced.  The floating
diagnostic value of the left side is `0.8262799834025526`; it is not used in
the proof.  As a separate exact diagnostic, the same witness also passes the
strict rational target `826279984/10^9` and fails `826279983/10^9`.  This is
reserved as a calibration observation rather than the campaign disposition;
the requested largest-safe-scale run remains to be done.

## Why the feasibility check is exact

Let `W=2^32`.  For every grouped transition weight `a_j`, the engine stores

```text
p_j = ceil(W a_j),       so a_j <= p_j/W exactly.
```

The witness `q` is a `uint32` vector with all entries in
`[992,299, 67,108,864]`.  For each of all 6,419,109 rows the verifier computes
the `uint64` integer

```text
R_i = sum_j p_j q[successor(i,j)]
```

and then scans

```text
R_i <= 1,468,159,907 q_i.
```

The maximum conservative row ratio is exactly the displayed lambda numerator;
the minimum floor ratio is `1,468,157,974`, giving a final fixed-point width of
1,933 units.  Therefore, componentwise,

```text
(A_z q)_i <= R_i/W <= lambda q_i.
```

There is no approximate-feasibility step.  The floating-point conversion used
while selecting the next integer iterate is only an optimizer; the saved
integer vector is accepted or rejected solely by the inequalities above.

## Explicit error and overflow budget

| item | certified amount |
|---|---:|
| stored witness error | 0 integer units |
| integer product/sum error | 0 integer units |
| component comparison error | 0 integer units |
| weight rounding direction | upward (conservative) |
| maximum single weight excess | `19643428001176716801879 / 10^32` |
| total two-character row-weight excess | `7756382093 / 2848351846400000000` |
| maximum possible full-row integer sum | 115,463,678,945,394,688 |
| `uint64` maximum | 18,446,744,073,709,551,615 |

The maximum single excess is about `1.9644e-10`, strictly below one `2^-32`
unit; the total possible row excess is about `2.7232e-9`.  These are not
subtracted as uncertain errors: upward rounding makes the checked matrix larger
than the theorem's exact matrix, so satisfying the larger inequality directly
implies the required one.

The logarithmic comparison is also exact.  `upper_engine.py` bounds each log
with rational partial sums of

```text
log(x) = 2 sum_{k>=0} y^(2k+1)/(2k+1),  y=(x-1)/(x+1),
```

and an exact rational geometric tail.  It decides the target only after the
lower and upper intervals separate.  Unit tests compare this decision against
literal rational powers on small cases.

## Generated automaton and saved witness

The author released source but no transition table or eigenvector.  The graph
was regenerated locally by `upper_graph_builder.c`, a direct C transcription
of paper Figure 7.

| artifact | bytes | SHA-256 |
|---|---:|---|
| `upper_graphs/h8/states.u64` | 51,352,872 | `c1288560c59890d29e181d445fb419ac639378001c9182ea7d5a21706320936f` |
| `upper_graphs/h8/transitions.u32` | 770,293,080 | `95d566129119c52aa003c1df4601cbfe172032854c942b8572e1e16df5d8bc87` |
| `checkpoints/upper-calibration-h8/state-1.npy` | 25,676,564 | `48c9b399a30f0bae01999d435af73f9a799a7e2a5c6d83aca69a280419dd2714` |

The combined authenticated graph identity is
`4c2514a4066e745d3da90a074cd1dbc5978eecd3259d795c00fd2f9313b8d084`.
The graph build took 29.57 seconds and occupies 786 MiB; the alternating
checkpoint occupies 49 MiB.

## Restart and run accounting

The run starts from a positive constant vector, writes alternating `.npy`
slots, hashes the completed slot, appends and `fsync`s one UTC JSON record to
`LOG.md`, and only then atomically commits `latest.json`.  A repeated sweep ID
is suppressed, making the commit window idempotent.

There are exactly 203 distinct upper `h=8` sweep records with sequential
iterations 1--203, from `2026-08-24T01:48:27Z` through
`2026-08-24T01:49:28Z`.  Their final sweep ID is
`1d1cb58020afd47f649e19e0756acb14491be7bed7cf457c42680a537a6178ed`.
Summed optimization time is 3.763 seconds and summed independent certificate
application time is 3.042 seconds.  The first run was safely interrupted after
iteration 1 while replacing an exact but unnecessarily huge power comparison;
resume continued from the authenticated slot and reached the final witness.

## Replay

```text
../.venv/bin/python upper_engine.py certify \
  --graph-dir upper_graphs/h8 \
  --checkpoint-dir checkpoints/upper-calibration-h8
```

The independent post-run invocation authenticated the graph, parameters, and
witness, recomputed the complete integer matrix-vector product, rescanned all
inequalities, re-proved the rational target, and returned `status: PASS`.

## Implementation cross-checks

`test_upper_engine.py` exhaustively compares the generated states and every
transition with `upper_oracle.py` for `h=2,3,4`, including the published counts
7, 98, and 1,020.  It compares five fixed-point sweeps with a literal Python
integer implementation, proves that upward-rounded products dominate the exact
rational operator, rejects a one-unit-too-small lambda, verifies split/resume
identity, and detects checkpoint tampering.

The combined task gate is:

```text
../.venv/bin/python -m unittest -v \
  test_upper_oracle.py test_upper_engine.py test_upper_contract.py
```

All 28 tests pass.
