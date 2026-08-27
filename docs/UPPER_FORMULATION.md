# Exact formulation for the Lueker upper-bound campaign

Date: 2026-08-24 UTC  
Scope: tracked upper task 001; source derivation and exact small-history oracle

## Correction to the initial shorthand

Lueker's 2009 upper-bound calculation is not the additive lower-operator
condition `T w <= w + c`.  The paper's actual finite certificate is the
componentwise Perron--Frobenius supersolution

```text
A_z v <= lambda v,       v(q) > 0 for every accepting state q,
0 < z < 1/k,             0 < lambda < 1.                 (paper (41))
```

Here `A_z` is the nonnegative weighted transition matrix of a finite automaton
that accepts a superset of the canonical decompositions into minimal match
pairs.  This distinction is material: the upper normalization is logarithmic,
not an additive constant divided by a normalizer.

The frozen primary sources are `sources/papers/lueker-2009.pdf` (SHA-256
`d812c50d68c1b7e6f7e63eb5537cc470aaad37e1cc93aa3c1d969dfc53398778`),
its extracted text, the author's `sources/lueker-code/code.pdf`, and the Java
sources under `sources/lueker-code/upper/`.

## The theorem chain

The following statements are facts from the paper, not implementation
assumptions.

1. Theorem 3.1 (`lueker-2009.txt` lines 401--407) converts a sufficiently small
   exponential count of pairs with LCS at least `yn` into `gamma_k <= y`.
2. Definition 3.2 and Theorem 3.3 (lines 482--534, equations (27)--(32)) say
   that if a finite-state machine covers all string pairs and the generating
   function of accepted lists obeys

   ```text
   f_l(z) <= K lambda(z)^l,
   ```

   then

   ```text
   gamma_k <= 2 log(k z) / log(lambda(z)).               (29)
   ```

3. Grouping the infinite minimal-match alphabet through `mu` gives the finite
   weights

   ```text
   w_{mu,z}(p) = sum_{p' in mu^-1(p)} z^size(p')          (36)
   ```

   and the recurrence `f_l(z) = A_z f_{l-1}(z)` in (37)--(38).
4. For the finite-history machine `M_h`, Lemmas 3.4--3.8 and Figure 7
   (`lueker-2009.txt` lines 660--968) prove that the machine never rejects a
   canonical decomposition and hence still covers every string pair.
5. Lines 970--977 state the computable certificate: because `A_z` is
   nonnegative, any strictly positive `v` satisfying (41) proves the required
   geometric bound.  This is a direct induction: `A_z v <= lambda v` implies
   `A_z^m v <= lambda^m v`; positivity of `v` supplies a finite constant `K`
   relating the all-ones initial vector to `v`.

For the binary alphabet the minimal match pairs are `T[c,l]`: when `l >= 0`,
the top is `(1-c)^l c` and the bottom is `c`; for `l < 0` the roles are
reversed.  Truncating each side to history `h` gives `l=-(h-1),...,h-1` and,
from the author's code overview page 5,

```text
w_{mu,z}(T[c,l]) = z^(|l|+2)          if |l| < h-1,
                    z^(h+1)/(1-z)     if |l| = h-1.
```

The tail term is a geometric series, so the finite matrix accounts for every
untruncated minimal match pair exactly.

## Exact normalization and target comparison

For binary `k=2`, both `2z` and `lambda` lie strictly between zero and one.
For positive integers `p,q`, careful multiplication by the negative
`log(lambda)` shows

```text
2 log(2z) / log(lambda) <= p/q
iff 2q log(2z) >= p log(lambda)
iff (2z)^(2q) >= lambda^p.
```

Thus a decimal target is never certified with floating-point logarithms.  The
campaign represents `z`, `lambda`, and `v` as exact rationals/fixed-point
integers, checks every row of (41) exactly, and compares the two rational
powers exactly.  In particular, Lueker's displayed `0.826280` means the exact
target `826280/1000000`, as stated in Section 3.2.2 lines 1005--1017.

## State and transition oracle

`upper_oracle.py` is a deliberately direct reference implementation of Figure
7, separate from the later production kernel:

- `UpperState(x,y,dx,dy)` stores the last `h` top/bottom bits and the last `h`
  vertical/horizontal LCS differences.
- `transition` reconstructs the two known table edges, appends one truncated
  minimal match pair, fills the newly exposed cells by the exact LCS
  recurrence, and performs the canonical up/left/match backtrack.
- Only the simultaneous bit-complement symmetry proved at paper lines
  860--865 is used.  Top/bottom exchange is intentionally not used because
  canonical tie-breaking destroys it.
- `build_automaton` performs literal breadth-first enumeration from
  `(0^h,0^h,1^h,1^h)`.
- `upper_contract.py` states the serialized proof contract independently of the production
  builder: exact start state and column alphabet, unique canonical complement-quotient
  representatives, successor closure, reachability, and reference completeness.
- `apply_operator`, `verify_feasible`, and `check_rational_upper_bound` use
  `fractions.Fraction` throughout.  No binary floating-point value can enter
  the oracle or its feasibility verdict.

The tests reproduce both Figure 5/6 transitions, the complete seven-state
`h=2` transition table in the author's code overview, and the published 98
accepting states at `h=3`.  They also build an exact all-ones certificate at
`z=1/5`, scan every row, reject a lambda smaller by exactly `10^-9`, reject
nonpositive/incomplete/nonrational witnesses, and exercise the exact power
normalization. Contract mutation tests separately reject spurious rejection, missing
successors, duplicate or missing start states, duplicate states, broken closure,
unreachable states, and incorrect quotient handling.

## Rounding and feasibility budget at this stage

| item | error |
|---|---:|
| state-transition arithmetic | 0 integer units |
| grouped match-pair weights | 0 rational units |
| matrix-vector products | 0 rational units |
| positivity checks | exact |
| componentwise feasibility comparisons | exact |
| logarithmic normalization comparison | exact rational powers |

The optimized engine may change storage and throughput, but it must remain
bit-for-bit equivalent to this oracle on small histories and must reduce its
final witness to the same exact inequalities before any upper bound is claimed.
