#!/bin/sh
# Build ASM wheel artifacts for release publishing.
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
RELEASE_DIR="$DIST_DIR/release"

if ! command -v uv >/dev/null 2>&1; then
    printf 'uv is required to build wheels: https://docs.astral.sh/uv/\n' >&2
    exit 1
fi

cd "$ROOT_DIR"
rm -rf "$DIST_DIR"
mkdir -p "$RELEASE_DIR"

uv build --wheel

WHEEL_PATH="$(ls "$DIST_DIR"/asm-*-py3-none-any.whl)"
cp "$WHEEL_PATH" "$RELEASE_DIR/"

if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$RELEASE_DIR"/*.whl > "$RELEASE_DIR/SHA256SUMS"
fi

printf 'Built wheel artifacts:\n'
printf '  %s\n' "$RELEASE_DIR"
printf 'Upload the versioned wheel to GitHub Releases.\n'
