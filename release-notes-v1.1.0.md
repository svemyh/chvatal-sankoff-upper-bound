# v1.1.0 release notes — PENDING

> **Release-candidate text only.** Path A has not run for this candidate. Do not publish,
> merge, tag, or create a GitHub release until every gate in
> `docs/RELEASE_V1.1.0_GATE.md` is approved at the exact frozen candidate SHA.

v1.1.0 keeps the theorem unchanged at
`gamma_2 <= 824443/1000000 = 0.824443`. It packages the corrected, reproducible
implementation and the self-contained manuscript without changing the certificate, graph
identity, witness bytes, or theorem value.

## What changed

- The bounded generation path is deterministic, uses integer-exact normalization, respects
  the selected C compiler, and runs in a frozen Python environment. This establishes a
  reproducible bounded capability; it is not a claim of a newly generated h=10 lineage.
- The manuscript is now self-contained and reproducibly built from pinned dependencies and
  deterministic figures.
- Scholarship and historical context are corrected: Dančík and Paterson introduced the
  automaton/generating-function method; Lueker's finite-history refinement supplies the
  certified comparison; and Qingqing Liu's dissertation report is distinguished from a
  previous peer-reviewed/certified record and from independently replayable certificate
  evidence.
- The default verifier is restricted to proof-critical certificate checks. Lineage,
  calibration, artifact provenance, and diagnostic controls are explicitly optional and do
  not become premises of the finite certificate.
- Bounded CI runs the 39-test suite, strict C11 and shell checks, exhaustive independent
  graph/oracle agreement through h=6, Lueker Table II reproduction through h=4, and a
  twice-repeated manuscript build. It does not fetch or build the h=8/h=10 replay artifacts.

## Reused v1.0.0 witness assets

This release reuses, without copying or re-uploading, the two byte-identical assets from the
[v1.0.0 witness release](https://github.com/svemyh/chvatal-sankoff-upper-bound/releases/tag/v1.0.0):

| asset | bytes | SHA-256 |
|---|---:|---|
| `upper-h10-state-0.npy` | 1,601,013,396 | `6501dd40a1894cfc4c8cd6cf2023078693ebe16a3e3158130e87d23f62afb6ba` |
| `upper-h10-q31-state-1.npy` | 1,601,013,396 | `e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436` |

`scripts/fetch_witness.sh` downloads those v1.0.0 assets and authenticates both exact
SHA-256 identities before use.

## Scope and limitations

No new deterministic h=10 checkpoint lineage is claimed. No exhaustive h=10
machine-semantics result is claimed: the supported semantics evidence remains exhaustive
agreement through h=6 plus the existing 760,000-transition h=10 spot-check. The separate
15,209,626,046-transition full-h10 oracle contract has not been run.

Path A, its evidence review, the candidate merge, the annotated `v1.1.0` tag, and the GitHub
release all remain **PENDING**.
