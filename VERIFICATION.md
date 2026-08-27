# How you can know this number is right

The claim is $\gamma_2 \le 0.824443$. This page explains, without requiring you to read any
code, why that can be checked rather than believed, and exactly where the remaining risk is.

## The idea that makes it checkable

Finding the answer was hard. Checking it is easy, and those are separate activities.

If you ask for the factors of 2,183, you will work for a while. If someone hands you
"37 × 59," you multiply and you *know*. You do not have to trust how they found it, whether
they were clever, lucky, or a machine.

This proof is the second thing. It is a table of 400,253,317 whole numbers, one per state of
a finite machine. Lueker proved a theorem in 2009 (J. ACM 56(3), eq. 41 and Thm 3.3) which
says: *if* such a table satisfies one simple inequality at every state, *then* the bound
follows. Nobody has to trust the search that produced the table, or us.

## The four things that must be true

| # | Claim | How it is established | Who is exposed |
|---|---|---|---|
| 1 | Lueker's theorem is correct | Peer-reviewed in the *Journal of the ACM*, standard in the field for 17 years | Not us |
| 2 | The inequality holds at all 400M states | Machine-checked in whole-number arithmetic; see below | Us, and it is checked |
| 3 | The final arithmetic is right | Logarithms bounded by exact rationals with proven remainders; the last step is an integer comparison | Us, and it is checked |
| 4 | We built the machine Lueker describes | The soft link. See "the honest weak point" | Us |

## Why the checker is not just saying yes

A verifier that always prints PASS proves nothing. Ours is made to prove it can fail:

- **Negative control.** The same table does *not* prove 0.824442, one notch better. So the
  checker discriminates instead of rubber-stamping.
- **Adversarial control.** Corrupt a single number in the table and the checker rejects it,
  naming the offending state. Run it yourself: it is part of `verify_upper.py`.
- **Sharpness control.** Run the whole pipeline at a smaller machine size and it certifies
  Lueker's published 0.826280 but *not* anything better. So the pipeline is not silently
  optimistic in our favour.

No floating-point number decides any inequality anywhere in the claim. Floats appear only in
printed diagnostics.

## The honest weak point, and what was done about it

The theorem is about a specific machine, so the machine's own correctness is a separate
obligation. A checksum proves our machine file was not altered; it does not prove the file
is *right*.

The dangerous direction is subtle. The operator drops "rejected" transitions from its row
sums, so a legitimate transition wrongly marked rejecting would make the machine look weaker
than reality and the bound come out **better** than the truth. That is an error that
flatters you, which is the kind worth hunting hardest.

Two independent defences, with an explicit remaining coverage limit:

**1. Transitions recomputed by a second implementation.**
`upper_oracle.py` is a separate, pure-Python transcription of Lueker's Figure 7, written to
be obviously correct rather than fast. `verify_graph_oracle.py` compares it against the C
builder:

- `exhaustive` — every state and every column for h=2..6 (1,979,120 transitions at h=6),
  including explicit start-state, uniqueness, quotient, closure, reachability, and
  completeness invariants.
- `sample` — a fast random subset, for anyone who wants a spot-check in minutes rather than
  hours (`h10-oracle-spotcheck.json`).
- `full` — a command for checking all 400,253,317 states and 15,209,626,046 transitions of
  the record graph. **This command exists but has not been run.** No
  `h10-oracle-full.json` has been produced or is cited as evidence. Its future inputs,
  schema, hashes, and acceptance gate are specified in `docs/FULL_H10_ORACLE.md`.

**2. Agreement with an external source.**
Writing more of our own code cannot rule out a *shared* misreading: if the builder and the
oracle both misread Figure 7 the same way, they agree and both are wrong. The only cure is
agreement with someone outside. Lueker's Table II publishes, for h = 2..8, the number of
accepting states and the resulting upper bound. `verify_lueker_table.py` rebuilds each
machine from scratch and checks both, certifying his bounds in exact arithmetic
(`lueker-table-ii-reproduction.json`):

| h | accepting states | Lueker's published bound |
|---|---|---|
| 2 | 7 | 0.845855 |
| 3 | 98 | 0.839250 |
| 4 | 1,020 | 0.835072 |
| 5 | 10,160 | 0.831910 |
| 6 | 89,960 | 0.829530 |
| 7 | 780,368 | 0.827727 * |
| 8 | 6,419,109 | 0.826280 |

All seven rows reproduce: every accepting-state count matches exactly, and every published
bound agrees with ours to the printed six decimals. These numbers were computed by a
different person, in a different language, seventeen years earlier. A transcription error
that still reproduces all seven is not a plausible failure mode.

\* Worth knowing if you try this yourself: **Table II is rounded to nearest, not rounded
up.** At h=7 the printed 0.827727 lies about 3e-7 *below* Lueker's own computed bound, so it
is not certifiable as an upper bound at its printed precision; the reproduction checks
two-sided agreement to six decimals instead, and reports which printed values are themselves
certifiable. At h=8 the rounding happens to go the other way, which is why our calibration
gate can certify 0.826280 outright.

## What is still not proven

Stated plainly, because a reader deserves to weigh it:

- **Faithfulness of the transcription is evidenced, not proven.** The seven-row agreement
  above is strong circumstantial evidence, not a formal proof that our machine *is* the
  machine in Lueker's Figure 7. Formalising that (in Lean, say) is the natural next step and
  has not been done.
- **The h=10 semantic comparison is sampled, not exhaustive.** The shipped spot-check covers
  760,000 of 15,209,626,046 transitions. The bounded h=2..6 checks are exhaustive; the future
  full-h10 gate has not been executed.
- **No external expert has reviewed this yet.** Everything here is machine-checked and
  independently replayed by the authors. That is not the same as a referee in this area
  reading the formulation.
- **Lueker's theorem itself is assumed**, as any paper building on the literature assumes
  its sources.

## Reproduce the whole chain yourself

```sh
uv sync --frozen
uv run --frozen python -m unittest -v \
  test_upper_engine.py test_upper_oracle.py test_upper_contract.py test_reproduction.py
uv run --frozen python verify_lueker_table.py \
  --max-history 4 --max-iterations 400 --tolerance-units 256 \
  --witness-scale 67108864 --threads 2
uv run --frozen python verify_graph_oracle.py exhaustive --max-history 6
```

Those bounded checks neither download nor build h=10. For the full claim replay, including
fresh graph/checkpoint roots and every artifact path, follow Path A in `REPRODUCE.md`.
`verify_graph_oracle.py full` remains a separate long job; `sample` gives most of its
assurance in minutes.
