#!/bin/sh
# Fetch the two large witness state files from the GitHub release and verify SHA-256.
set -eu
cd "$(dirname "$0")/.."
REPO="svemyh/chvatal-sankoff-upper-bound"
TAG="v1.0.0"

fetch() {
  asset="$1"; dest="$2"; sha="$3"
  if [ -f "$dest" ]; then
    echo "exists: $dest"
  elif command -v gh >/dev/null 2>&1; then
    gh release download "$TAG" --repo "$REPO" --pattern "$asset" --output "$dest"
  else
    curl -fL -o "$dest" "https://github.com/$REPO/releases/download/$TAG/$asset"
  fi
  actual=$(shasum -a 256 "$dest" | cut -d' ' -f1)
  [ "$actual" = "$sha" ] || { echo "SHA-256 MISMATCH for $dest"; exit 1; }
  echo "ok: $dest"
}

fetch upper-h10-state-0.npy checkpoints/upper-h10/state-0.npy \
  6501dd40a1894cfc4c8cd6cf2023078693ebe16a3e3158130e87d23f62afb6ba
fetch upper-h10-q31-state-1.npy checkpoints/upper-h10-q31/state-1.npy \
  e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436
echo "witness complete"
