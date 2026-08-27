# Bounded continuous integration

`.github/workflows/ci.yml` runs on every pull request, every push to `main`, and manual
dispatch. It uses Ubuntu 24.04, GCC, uv 0.10.2, CPython 3.11.14, the frozen `uv.lock`, and
read-only repository permissions. The only actions are checkout and Astral's uv installer,
both pinned by immutable commit SHA. The Tectonic 0.15.0 Linux archive is authenticated by
SHA-256 before use.

The bounded job proves that:

- all 56 current unit, contract, clean-clone reproduction, and Path A preflight tests pass;
- all four C helpers/builders parse and compile under C11 with GCC warnings treated as
  errors, including the supported `unsigned __int128` extension;
- both repository shell scripts parse as POSIX shell;
- the independent pure-Python oracle agrees with the C graph builder for every state and
  transition through h=6 (1,979,120 transitions at h=6), including start-state, uniqueness,
  canonical quotient, successor closure, reachability, and completeness checks;
- the verifier-owned matrix-free C oracle agrees byte-for-byte with every production-builder
  transition through h=6, and its corruption, overflow, closure, reject, and checkpoint
  failure paths are exercised;
- the documented Lueker Table II reproduction agrees through h=4; and
- the figures and manuscript build twice with identical hashes, match the checked-in PDFs,
  parse successfully, contain pages, and expose the expected title and bound as text.

The h=6 oracle runs on every pull request because a clean local measurement completed in
under 30 seconds; there is no reduced or scheduled variant.

CI does **not** download the h=10 state table or witness, replay the 400,253,317-state
certificate, run the 15.2-billion-transition h=10 matrix-free scan, perform a new h=10 power
iteration or parameter search, attempt h=11, or prove the independent implementations did
not share the same transcription error. Those remain separate obligations described in
`VERIFICATION.md` and `docs/FULL_H10_ORACLE.md`.
