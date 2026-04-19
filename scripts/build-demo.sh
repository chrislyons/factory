#!/usr/bin/env bash
# Build script for static demo deployment (Cloudflare Pages, Vercel, Netlify, etc.)
# Usage: VITE_DEMO_MODE=true bash scripts/build-demo.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
PORTAL_DIR="$REPO_ROOT/portal"

echo "── Installing pnpm ──"
npm install -g pnpm@latest

echo "── Installing dependencies ──"
cd "$PORTAL_DIR"
pnpm install --frozen-lockfile

echo "── Building (demo mode) ──"
VITE_DEMO_MODE="${VITE_DEMO_MODE:-true}" pnpm build

echo "── Fixing entry points ──"
cp "$PORTAL_DIR/dist/portal.html" "$PORTAL_DIR/dist/index.html"

# Deep-link fallback: copy each page HTML into a subdirectory so
# /pages/jobs works as /pages/jobs/ on static hosts
cd "$PORTAL_DIR/dist/pages"
for f in *.html; do
  name="${f%.html}"
  mkdir -p "$name"
  cp "$f" "$name/index.html"
done

echo "── Done ──"
echo "Output: $PORTAL_DIR/dist/"
find "$PORTAL_DIR/dist" -name "index.html" | sort
