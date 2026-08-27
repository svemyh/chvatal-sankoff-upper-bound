#!/bin/sh
# Populate a fresh checkpoint root and fetch the two large witness state files.
set -eu
cd "$(dirname "$0")/.."
REPO="svemyh/chvatal-sankoff-upper-bound"
TAG="v1.0.0"
CHECKPOINT_ROOT="${1:-}"

if [ -z "$CHECKPOINT_ROOT" ]; then
  echo "usage: scripts/fetch_witness.sh FRESH_CHECKPOINT_ROOT" >&2
  exit 2
fi

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "need sha256sum or shasum to authenticate downloads" >&2
    exit 2
  fi
}

mkdir -p "$CHECKPOINT_ROOT/upper-calibration-h8" \
  "$CHECKPOINT_ROOT/upper-h10" "$CHECKPOINT_ROOT/upper-h10-q31"
cp checkpoints/upper-calibration-h8/* "$CHECKPOINT_ROOT/upper-calibration-h8/"
cp checkpoints/upper-h10/parameters.json checkpoints/upper-h10/latest.json \
  "$CHECKPOINT_ROOT/upper-h10/"
cp checkpoints/upper-h10-q31/parameters.json checkpoints/upper-h10-q31/latest.json \
  "$CHECKPOINT_ROOT/upper-h10-q31/"

fetch() {
  asset="$1"; dest="$2"; sha="$3"
  if [ -f "$dest" ]; then
    echo "exists: $dest"
  elif command -v gh >/dev/null 2>&1; then
    gh release download "$TAG" --repo "$REPO" --pattern "$asset" --output "$dest"
  else
    curl -fL -o "$dest" "https://github.com/$REPO/releases/download/$TAG/$asset"
  fi
  actual=$(sha256_file "$dest")
  [ "$actual" = "$sha" ] || { echo "SHA-256 MISMATCH for $dest"; exit 1; }
  echo "ok: $dest"
}

fetch upper-h10-state-0.npy "$CHECKPOINT_ROOT/upper-h10/state-0.npy" \
  6501dd40a1894cfc4c8cd6cf2023078693ebe16a3e3158130e87d23f62afb6ba
fetch upper-h10-q31-state-1.npy "$CHECKPOINT_ROOT/upper-h10-q31/state-1.npy" \
  e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436
echo "witness complete"
