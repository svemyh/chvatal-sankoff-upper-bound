# Changelog

This project uses the top-level `VERSION` file for release metadata. The Python project
version remains `0.0.0` because `pyproject.toml` describes a non-packaged reproducibility
environment rather than a published distribution.

## [1.1.0] — Release candidate (unreleased)

The theorem is unchanged at `gamma_2 <= 0.824443`. This candidate remains blocked on the
pending Path A gate in `docs/RELEASE_V1.1.0_GATE.md`; it is not a tag or GitHub release.

### Added

- Locked, portable reproduction environments for the implementation and manuscript, with
  deterministic bounded generation and integer-exact normalization.
- Builder-independent graph contracts, an independent Figure 7 oracle, all seven rows of
  the Lueker Table II reproduction, and an unexecuted future full-h10 oracle contract.
- A self-contained eight-page manuscript, reproducible figures and PDF build, plain-language
  verification guide, read-only Path A preflight, and explicit release-evidence gate.
- Bounded GitHub CI covering the 39-test suite, strict C11 and shell checks, exhaustive
  graph/oracle agreement through h=6, Table II reproduction through h=4, and twice-repeated
  manuscript builds.

### Fixed / corrected

- Separated the proof-critical certificate replay from optional provenance, lineage,
  calibration, and diagnostic evidence; added explicit mutation and read-only contracts.
- Corrected scholarship to distinguish the Dančík–Paterson method, Lueker's finite-history
  refinement and certified record, and Qingqing Liu's separately reported dissertation
  result from the previous peer-reviewed/certified record and independently replayable
  certificate evidence.
- Corrected numerical wording, resource requirements, figures, rounding caveats, fresh-root
  witness handling, and the prior implication that a full h=10 semantics check had run.
- Made the current manuscript and verifier contracts self-contained without changing the
  certificate, graph identity, witness bytes, theorem, or documented command-line entry points.

### Verification

- Bounded CI and local checks deliberately avoid downloading or building h=8/h=10 replay
  artifacts and do not run power iteration, the full h=10 oracle, or h=11 work.
- Deterministic from-scratch generation is verified only at bounded histories; no new
  deterministic h=10 checkpoint lineage is claimed.
- Exhaustive oracle agreement is established through h=6, with the existing 760,000-transition
  h=10 spot-check; no exhaustive h=10 machine-semantics result is claimed.
- Path A replay, evidence review, merge, tag, and GitHub release all remain pending at the
  exact frozen candidate SHA.
