# v1.1.0 Path A release gate

## Status: PENDING

This is an executable release gate, not a completed evidence record. The expensive Path A
replay was **not** run while adding this document. No h=8 or h=10 graph or witness was built
or downloaded, no power iteration or h=10 oracle was run, and no tag, GitHub release, or
asset upload was created. v1.1.0 remains blocked until every gate below is run against one
frozen release-candidate commit and its evidence is reviewed.

The theorem value is unchanged:

```text
gamma_2 <= 0.824443
```

## Release baseline and version decision

The existing `v1.0.0` is a lightweight tag at commit
`7cff310d1e706c47ced0802aff869915eea59845`. Corrected `main` at the time this gate was
prepared is `fa3b101b458cbe2ca8c2c370bbef0e7f5ac94bbb`, seven commits ahead:

| commit / PR | non-breaking change since `v1.0.0` |
|---|---|
| `5e56a41` | Added the still-unrun full-h10 oracle mode, the independent Table II checker, and a plain-language trust-chain account. |
| `40fae11` | Recorded all seven rows of the Lueker Table II reproduction and its rounding caveat. |
| `989f3e1` / PR #1 | Locked the Python environment, made bounded generation deterministic and portable, added exact normalization, fresh-root replay, and bounded reproduction tests. |
| `27bd52f` / PR #2 | Split proof-critical replay from optional provenance, added explicit graph contracts and mutation tests, and corrected the unperformed full-h10-oracle claim. |
| `dac3352` / PR #3 | Corrected scholarship, numerical prose, resource claims, and figures; added a reproducible manuscript build. |
| `e2e5865` / PR #5 | Added SHA-pinned, read-only bounded CI for tests, strict C11, shell syntax, exhaustive h<=6 oracle agreement, Table II through h=4, and reproducible PDFs. |
| `fa3b101` / PR #4 | Made the finite-history method and exact proof obligation self-contained in the manuscript. |

The v1.0.0 tag therefore identifies source and a five-page manuscript that predate the
corrected verifier contracts, deterministic bounded implementation, locked environment,
bounded CI, scholarship corrections, and current eight-page self-contained manuscript.
The release assets are still valid, but the source automatically shown with the v1.0.0 tag
is not the corrected/reproducible source now on `main`. That source/tag mismatch is the
reason to cut a corrected release rather than silently treating v1.0.0 as current.

`v1.1.0` is the appropriate non-breaking release: it adds substantial verification,
reproducibility, CI, and manuscript capabilities while preserving the theorem constant,
certificate, graph identity, witness bytes, and documented command-line entry points. A
patch number would understate that new auditable surface; a major number would incorrectly
signal an incompatible theorem or interface change.

## Existing witness assets: reuse, do not duplicate

The v1.0.0 GitHub release contains exactly these two witness assets:

| asset | bytes | SHA-256 |
|---|---:|---|
| `upper-h10-state-0.npy` | 1,601,013,396 | `6501dd40a1894cfc4c8cd6cf2023078693ebe16a3e3158130e87d23f62afb6ba` |
| `upper-h10-q31-state-1.npy` | 1,601,013,396 | `e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436` |

They total 3,202,026,792 bytes (about 3.0 GiB). The corrected verifier still expects the
second hash as the record witness, and `scripts/fetch_witness.sh` already downloads both
files from `v1.0.0` and authenticates these exact identities.

**Decision:** v1.1.0 reuses these v1.0.0 assets through the existing fetch script. Do not
copy or re-upload 3.2 GB of identical data to the v1.1.0 release. The v1.1.0 notes must link
to the v1.0.0 witness release, list both hashes, and say that the bytes are reused. Any hash
change is not v1.1.0 housekeeping: it is a new result requiring a separate review.

## What Path A proves, and what it does not

Path A authenticates the shipped graph and witness, then scans the certificate inequality
for every one of the 400,253,317 h=10 graph rows in integer-exact arithmetic. With
`--with-provenance`, it also checks the h=8 calibration, lineage/rescale metadata, benchmark,
saved certificate, negative sharpness control, and witness-tampering control. This is the
full row-by-row certificate inequality replay supporting the unchanged theorem value.

Path A does **not** independently recompute the semantics of every graph transition. The
separate `verify_graph_oracle.py full` contract would compare 15,209,626,046 h=10
transitions against the independent Python machine-semantics oracle. That exhaustive h=10
oracle has still not been performed and is not a v1.1.0 gate. The supported statement after
a successful Path A replay remains: exhaustive oracle agreement through h=6, a
760,000-transition h=10 spot-check, and no exhaustive h=10 semantics result. See
`docs/FULL_H10_ORACLE.md`.

## Gate 1: freeze the candidate and pass bounded CI

1. Open the release-candidate PR and stop pushing to it.
2. Record the full 40-hex PR head as `CANDIDATE_SHA`.
3. Require both `Bounded CI / Tests and bounded contracts` and
   `Bounded CI / Reproducible manuscript` to succeed at that exact SHA.
4. Record each check's GitHub Actions URL. A green run at a different SHA is not evidence.

The bounded jobs intentionally do not download or build h=8/h=10 replay artifacts. They
must complete before scarce replay resources are allocated.

## Gate 2: read-only Path A resource preflight

Use a clean clone on a host with at least 80 GiB free at the future replay destination and
at least 64 GiB installed RAM. The replay is expected to take about 90 minutes, the h=10
graph consumes about 60 GB, and the recorded verifier peak was about 41 GiB RSS. The
preflight uses no override flags and does not create the output destination, synchronize an
environment, fetch assets, or build graphs.

```bash
set -o pipefail
git fetch origin
git switch --detach "$CANDIDATE_SHA"
test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"

REPLAY_ROOT="$PWD/reproduction/v1.1.0-path-a-$CANDIDATE_SHA"
EVIDENCE_ROOT="$PWD/../v1.1.0-path-a-evidence-$CANDIDATE_SHA"
test ! -e "$EVIDENCE_ROOT"
mkdir -p "$EVIDENCE_ROOT"

python3 scripts/preflight_path_a.py \
  --expected-commit "$CANDIDATE_SHA" \
  --output-root "$REPLAY_ROOT" \
  | tee "$EVIDENCE_ROOT/preflight.json"
PREFLIGHT_PIPE=("${PIPESTATUS[@]}")
test "${PREFLIGHT_PIPE[0]}" -eq 0
test "${PREFLIGHT_PIPE[1]}" -eq 0
```

The command must exit zero with top-level JSON `status: "PASS"`. It verifies the exact
candidate SHA, a fully clean worktree, an absent replay destination, 80 GiB free disk,
64 GiB RAM, uv 0.10.2, `uv lock --check`, the C compiler, strict C11 syntax for all three C
sources, and unchanged Git status before/after. Any failed check aborts the gate.

## Gate 3: exact Path A replay at the candidate SHA

Run the existing Path A machinery unchanged. This builds graphs and replays the shipped
witness; it does not run power iteration.

```bash
set -o pipefail
{
  set -eux
  date -u
  uname -a
  git rev-parse HEAD
  git status --porcelain --untracked-files=no
  uv --version
  ${CC:-cc} --version

  uv sync --frozen
  uv run --frozen python -VV
  uv run --frozen python -c \
    'import numpy,numba,llvmlite; print(numpy.__version__, numba.__version__, llvmlite.__version__)'

  test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"
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
  uv run --frozen python verify_upper.py --with-provenance \
    --graph-root "$REPLAY_ROOT/upper_graphs" \
    --checkpoint-root "$REPLAY_ROOT/checkpoints"
} 2>&1 | tee "$EVIDENCE_ROOT/path-a-transcript.txt"
PATH_A_PIPE=("${PIPESTATUS[@]}")
test "${PATH_A_PIPE[0]}" -eq 0
test "${PATH_A_PIPE[1]}" -eq 0
```

Both verifier invocations must emit top-level JSON `status: "PASS"`, `read_only: true`, and
`proof_critical_scope: "PASS"`. The second must also emit
`optional_provenance_scope: "PASS"`. Both must end with exactly:

```text
PASS: exact feasible witness proves gamma_2 <= 0.824443 < 0.826280
```

The h=10 record evidence must report 400,253,317 states, graph identity
`e4db7c10b0b55060c3a9beff010583a593b4c24bc13600ecb219b933a2806f7a`, witness SHA-256
`e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436`, and no failing
state. The authenticated h=10 graph files must have these hashes:

| graph file | bytes | SHA-256 |
|---|---:|---|
| `states.u64` | 3,202,026,536 | `defc127da935708620977efddda218378322d9d23921ac3453c9f7a56ff5f59b` |
| `transitions.u32` | 60,838,504,184 | `611a32eb44baa93fbe5231aa8ddaf9aa690da4e4b2a049ff54226ce3e265aba5` |

## Gate 4: capture and review evidence

Evidence is external to the repository and must contain facts from the completed run, not a
pre-filled success template. Capture all generated graph, witness, metadata, saved
certificate, manuscript, and figure identities plus the environment and Git state:

```bash
uv run --frozen python - "$REPLAY_ROOT" > "$EVIDENCE_ROOT/artifact-sha256.txt" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

repo = Path.cwd()
replay = Path(sys.argv[1])
paths = [
    *sorted((replay / "upper_graphs").glob("**/*")),
    *sorted((replay / "checkpoints").glob("**/*")),
    repo / "upper-h10-certificate.json",
    repo / "paper/cs_upper_bound.pdf",
    repo / "paper/fig_history.pdf",
    repo / "paper/fig_scaling.pdf",
    repo / "uv.lock",
]
for path in paths:
    if not path.is_file():
        continue
    digest = sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 << 20):
            digest.update(block)
    print(digest.hexdigest(), path.stat().st_size, path)
PY

pdfinfo paper/cs_upper_bound.pdf > "$EVIDENCE_ROOT/manuscript-pdfinfo.txt"
test "$(pdfinfo paper/cs_upper_bound.pdf | awk '/^Pages:/ {print $2}')" = 8

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}
test "$(sha256_file paper/cs_upper_bound.pdf)" = \
  95fd81703ac7958978649013536f266a821b65ab2a8f0244d535a81e37894275
test "$(sha256_file upper-h10-certificate.json)" = \
  523fb826c7c7e18310cb1625a04d375017ed228bef911063634022560ff012ff

gh pr checks "$PR_NUMBER" --json name,state,link \
  > "$EVIDENCE_ROOT/ci-checks.json"
gh run list --workflow ci.yml --commit "$CANDIDATE_SHA" \
  --json databaseId,headSha,status,conclusion,url \
  > "$EVIDENCE_ROOT/ci-runs.json"

git rev-parse HEAD > "$EVIDENCE_ROOT/candidate-sha.txt"
git status --porcelain --untracked-files=no > "$EVIDENCE_ROOT/tracked-status.txt"
git diff --exit-code
git diff --cached --exit-code
test ! -s "$EVIDENCE_ROOT/tracked-status.txt"
```

The reviewer must confirm:

- `candidate-sha.txt`, both CI head SHAs, `preflight.json`, and the transcript all identify
  the same `CANDIDATE_SHA`;
- both required CI checks succeeded and their URLs are present;
- the transcript is complete, both verifier invocations passed, and no command failed;
- graph, both reused witness, saved certificate, lock, PDF, and figure hashes are present;
- the manuscript is eight pages with the expected SHA-256 above; and
- no tracked artifact changed during the replay.

Hash the evidence directory itself (for example, a deterministic archive) and retain that
archive and digest with the release review. Do not commit 60+ GB replay outputs.

## Abort criteria

The release remains PENDING and no tag or release may be created if any of these occurs:

- the candidate branch receives another commit after CI or replay evidence was captured;
- the preflight fails, the replay destination already exists, or disk/RAM is below the
  required floor;
- uv, the frozen lock, compiler, graph build, asset authentication, verifier, provenance
  controls, hash checks, PDF checks, or required CI returns nonzero or differs from the
  pinned identity;
- the process is killed, swaps into unsafe resource pressure, runs out of disk/RAM, or the
  transcript is truncated;
- any tracked file changes before or during replay;
- evidence is missing the exact commit, environment, command transcript, artifact hashes,
  verifier output, CI URLs, PDF hash/page count, or clean tracked-tree confirmation; or
- the integration step changes the release tree without rerunning Path A at the new SHA.

Partial output is failure evidence only. Delete or move it aside before retrying; never
resume into a destination that the preflight did not prove absent.

## Release sequencing after evidence approval

1. Freeze the candidate PR and record `CANDIDATE_SHA`.
2. Pass both required bounded CI jobs at exactly that SHA and record their URLs.
3. Run the read-only preflight, then Path A at exactly that SHA.
4. Review and approve the complete evidence bundle.
5. Merge the PR if the candidate is not already on `main`. Record `RELEASE_SHA`. If the
   integration creates a different commit, require an identical source tree:

   ```sh
   CANDIDATE_TREE="$(git rev-parse "$CANDIDATE_SHA^{tree}")"
   RELEASE_TREE="$(git rev-parse "$RELEASE_SHA^{tree}")"
   test "$CANDIDATE_TREE" = "$RELEASE_TREE"
   ```

   If the trees differ, rerun bounded CI and Path A at `RELEASE_SHA` and review new
   evidence.
6. Only then create and push an **annotated** `v1.1.0` tag at the gated `RELEASE_SHA`.
7. Create the GitHub release from that tag with the conservative notes below and no witness
   uploads. Verify the release is public, non-draft, non-prerelease, targets the annotated
   tag, shows the expected source tree, links to the v1.0.0 witnesses, and has no duplicate
   large assets.

Future tag/release commands, to be run only after the gate changes from PENDING to approved:

```sh
git tag -a v1.1.0 "$RELEASE_SHA" -m "v1.1.0: corrected reproducible release"
git push origin v1.1.0
test "$(git cat-file -t v1.1.0)" = tag
test "$(git rev-parse 'v1.1.0^{commit}')" = "$RELEASE_SHA"
gh release create v1.1.0 --verify-tag --title "v1.1.0" --notes-file release-notes-v1.1.0.md
gh release view v1.1.0 --json tagName,targetCommitish,isDraft,isPrerelease,url,assets
```

## Conservative v1.1.0 release-note wording

Use this substance without upgrading the claims:

> v1.1.0 keeps the theorem constant unchanged at `gamma_2 <= 0.824443`. It releases the
> corrected, reproducible implementation and self-contained manuscript: a frozen toolchain,
> exact bounded normalization, explicit verifier/graph contracts, bounded independent
> checks and CI, corrected scholarship and resource claims, and a reproducible PDF build.
>
> The release reuses the two byte-identical v1.0.0 witness assets; their SHA-256 values are
> `6501dd40a1894cfc4c8cd6cf2023078693ebe16a3e3158130e87d23f62afb6ba` and
> `e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436`.
>
> This release does not claim a newly generated deterministic h=10 lineage. It also does
> not claim completion of the separate 15,209,626,046-transition exhaustive h=10
> machine-semantics oracle. Path A replays the shipped certificate inequality row by row;
> the documented h=10 semantics limitation remains.
