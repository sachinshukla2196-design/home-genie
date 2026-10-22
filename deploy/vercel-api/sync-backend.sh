#!/usr/bin/env bash
# Copies the backend source into this Vercel project before `vercel deploy`.
# The copy is git-ignored; backend/ stays the single source of truth.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
rm -rf "$here/backend"
mkdir -p "$here/backend"
cp "$here/../../backend/"*.py "$here/backend/"
echo "Copied $(ls "$here/backend" | wc -l) backend modules."
