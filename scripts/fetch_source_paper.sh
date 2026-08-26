#!/bin/sh
# Obtain the primary source (Lueker, J. ACM 56(3), 2009) and authenticate it.
# The PDF is ACM-copyrighted and is deliberately NOT redistributed in this
# repository.  Fetch it through your own institutional or ACM DL access and
# place it at sources/papers/lueker-2009.pdf; this script then verifies that
# the bytes match the copy the certificate was derived from.
set -eu
cd "$(dirname "$0")/.."
DEST="sources/papers/lueker-2009.pdf"
SHA="d812c50d68c1b7e6f7e63eb5537cc470aaad37e1cc93aa3c1d969dfc53398778"
mkdir -p sources/papers
if [ ! -f "$DEST" ]; then
  echo "Place the paper at $DEST first."
  echo "  DOI:  10.1145/1516512.1516519"
  echo "  ACM:  https://dl.acm.org/doi/10.1145/1516512.1516519"
  exit 1
fi
actual=$(shasum -a 256 "$DEST" | cut -d' ' -f1)
if [ "$actual" = "$SHA" ]; then
  echo "ok: $DEST matches the pinned source ($SHA)"
else
  echo "SHA-256 MISMATCH"; echo "  expected $SHA"; echo "  actual   $actual"; exit 1
fi
