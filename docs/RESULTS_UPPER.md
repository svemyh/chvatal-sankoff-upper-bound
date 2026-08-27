# A rigorous improved upper bound for the binary Chvátal--Sankoff constant

Date: 2026-08-24 UTC  
Method: Lueker's finite-history feasible-function certificate  
Disposition: **strict improvement certified**

## Result

The binary Chvátal--Sankoff constant satisfies

```text
gamma_2 <= 824443/1000000 = 0.824443 < 0.826280.
```

The inequality is certified by a positive integer feasible function on the
complete `h=10` Lueker automaton.  The automaton has 400,253,317 accepting
states and 38 grouped transition columns.  Every componentwise feasibility
constraint was checked with integer arithmetic after authenticating the graph
and witness by SHA-256.

The exact certificate parameters are

```text
z                         3209/10000
lambda                    1464651560/4294967296
history                    10
states                     400253317
final iteration            113
final ratio width          2019/2^32
graph identity             e4db7c10b0b55060c3a9beff010583a593b4c24bc13600ecb219b933a2806f7a
witness SHA-256             e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436
```

The descriptive real value of Lueker's normalization is
`0.824442457097411...`.  This decimal was not used to certify the result.  The
verifier proves the rational target `824443/1000000` and separately confirms
that the next smaller six-decimal target `824442/1000000` does not follow from
this witness.

## Source-exact theorem and normalization

The primary source is the frozen local copy of Lueker's 2009 JACM paper,
`sources/papers/lueker-2009.pdf`, SHA-256
`d812c50d68c1b7e6f7e63eb5537cc470aaad37e1cc93aa3c1d969dfc53398778`.
The full extraction is in `UPPER_FORMULATION.md`.

The paper's actual upper certificate is equation (41), not an additive
lower-operator inequality:

```text
A_z v <= lambda v,       v_i > 0,       0 < z < 1/2,       0 < lambda < 1.
```

Theorem 3.3 and equation (29) then give, for the binary alphabet,

```text
gamma_2 <= 2 log(2z) / log(lambda).
```

For an exact rational target `p/q`, since `2z` and `lambda` are both in
`(0,1)`, the comparison is

```text
2 log(2z) / log(lambda) <= p/q
iff (2z)^(2q) >= lambda^p.
```

The verifier decides the equivalent log inequality using rational partial sums
of the atanh series and a rational geometric remainder bound.  No
floating-point logarithm participates in the verdict.

## Mandatory calibration: reproduction of `0.826280`

Before the record-scale run, the implementation reproduced Lueker's published
Table II calculation at `h=8` and `z=3209/10000`:

```text
states                      6419109
lambda                      1468159907/4294967296
witness range               992299..67108864
ratio width                 1933/2^32
target                      826280/1000000: PASS
witness SHA-256             48c9b399a30f0bae01999d435af73f9a799a7e2a5c6d83aca69a280419dd2714
```

The optional provenance replay (`verify_upper.py --with-provenance`) rehashes the `h=8`
graph and checkpoint, recomputes all
6,419,109 integer row sums, finds no failing state, and re-proves the exact
`0.826280` target.  This calibration gate was completed before the larger
history was selected or run.  Detailed evidence is in
`UPPER_CALIBRATION.md`.

## Largest safe local scale

Exact breadth-first closures and complete kernel benchmarks were performed at
`h=8,9,10`.  Under the mandatory 20 GiB reserve rule, `h=10` was the largest
safe history on the 128 GiB host:

| item | exact/measured value |
|---|---:|
| `h=10` graph bytes | 64,040,530,720 |
| live two-witness-plus-row-sum bytes | 6,404,053,072 |
| two checkpoint slots | 3,202,026,792 |
| minimum measured available memory | 72,842,645,340 |
| required reserve | 21,474,836,480 |
| benchmark peak RSS | 57,421,414,400 |

`h=11` was rejected before allocation.  Its conservative builder plan required
131,897,453,928 bytes and missed the reserve by exactly 80,529,645,068 bytes
(74.9991 GiB); no `upper_graphs/h11` directory exists.  The optional provenance replay
recomputes the reserve inequalities from `upper-benchmark-results.json` and
authenticates the selected `h=10` identity.  See `UPPER_BENCHMARKS.md`.

## Exact feasibility proof

For each exact rational grouped weight `a_j`, the production representation is

```text
W_j = ceil(2^32 a_j).
```

For every state `i`, rejecting transitions are omitted and the verifier
computes

```text
S_i = sum_j W_j V[successor(i,j)]
```

as a uint64 integer.  The complete scan establishes

```text
S_i <= 1464651560 V_i
```

for all 400,253,317 states.  Because `W_j/2^32 >= a_j` entrywise,

```text
A_z V <= (1464651560/2^32) V.
```

The independent replay obtains:

```text
failing state               -1 (none)
maximum ceiling ratio       1464651560
minimum floor ratio         1464649541
ratio width                 2019 <= 2048 stopping gate
maximum actual row sum      3145313150651095756
witness range               9834007..2147483648
```

The stopping width is a conservative convergence diagnostic, not a substitute
for feasibility.  Exact feasibility and exact rational target passage were
both separately required.

## Complete rounding and feasibility budget

| quantity | certified treatment |
|---|---|
| state and transition generation | exact bit/integer recurrence |
| graph storage | exact uint64 states and uint32 successors, SHA-256 authenticated |
| grouped weights before storage | exact `Fraction` values |
| stored weight direction | upward, `ceil(2^32 a_j)` |
| maximum one-column weight excess | `19643428001176716801879/10^32` |
| sum of all 38 stored-column excesses | `13061850843/2848351846400000000` |
| saved witness | exact positive uint32 integers |
| stored-witness error | 0 integer units |
| integer product/sum error | 0 integer units |
| feasibility-comparison error | 0 integer units |
| target comparison | exact rational intervals |

The coefficient excesses are conservative: the checked matrix is entrywise
larger than Lueker's exact matrix.  They are therefore not uncertain errors
that need to be subtracted.  Passing the enlarged integer inequality directly
implies the theorem's inequality.

The worst possible full-row integer sum is
3,694,837,743,432,499,200, leaving 14,751,906,330,277,052,415 below the uint64
maximum.  The saved witness and every intermediate product are thus within the
preflighted integer range.  Floating point was used only to propose successive
witnesses; every proposal was accepted solely by a fresh integer scan.

## Restart safety and run evidence

Sweeps 1--100 used witness scale `Q=2^26`.  The exact record target had already
passed, but quantization left the ratio width near 10,000 units.  The stopping
gate was not relaxed.  Instead, the iteration-100 witness was multiplied
exactly by 32 into a transactional `Q=2^31` child checkpoint, and sweeps
101--113 continued from it.

The optional provenance replay reconstructs the complete rescaled `.npy` byte stream and checks
the chain

```text
iteration-100 parent        6501dd40a1894cfc4c8cd6cf2023078693ebe16a3e3158130e87d23f62afb6ba
factor                      32
rescaled child              bcba07e3635ab2a0be4520d6b737366eaa55006dc4b42d76fc9c6690c0a3506f
final iteration-113 child   e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436
```

`LOG.md` contains exactly one authenticated UTC sweep entry for every `h=8`
iteration 1--203 and every `h=10` iteration 1--113.  All are feasible and all
sweep IDs are unique.  The complete record run plus rescale took 10,265.32
seconds (2.85148 hours) and peaked at 60,317,810,688 bytes RSS (56.1753 GiB),
with zero swaps.  Further timing and transition-range evidence is in
`UPPER_H10_RESULT.md`.

## Standalone read-only replay

Under the pinned environment, run:

```text
uv run --frozen python verify_upper.py \
  --graph-root reproduction/shipped-v1.0.0/upper_graphs \
  --checkpoint-root reproduction/shipped-v1.0.0/checkpoints
```

The locked environment supplies NumPy and Numba. The verifier disables bytecode writes and
the default command snapshots every proof-critical artifact before and after the replay to enforce read-only
behavior. See `REPRODUCE.md` for creating the fresh roots without relying on absent arrays
under the tracked checkpoint metadata directories.

The proof-critical default independently:

1. authenticates and rescans the complete `h=10` record witness;
2. checks witness positivity and scale, successor closure, rounding, and uint64 preflights;
3. proves every integer feasibility inequality; and
4. proves `824443/1000000` exactly.

Run the same command with `--with-provenance` to additionally authenticate the frozen paper
when present, benchmark, saved certificate JSON, h=8 calibration, all 316 logged sweeps, and
the exact `Q=2^26` to `Q=2^31` migration. It also runs the negative control rejecting
`824442/1000000`. These records establish lineage and diagnostics; they are not premises of
the certificate inequality.

The replay ends with:

```text
PASS: exact feasible witness proves gamma_2 <= 0.824443 < 0.826280
```

## Immutable record artifact identities

| artifact | SHA-256 |
|---|---|
| `upper-h10-certificate.json` | `523fb826c7c7e18310cb1625a04d375017ed228bef911063634022560ff012ff` |
| `upper-benchmark-results.json` | `e64193e8d6bd717d251452b090d941c426abbcd9db4f61eaddb03e0da517554d` |
