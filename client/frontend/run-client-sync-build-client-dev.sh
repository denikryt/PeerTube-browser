#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_CLIENT_DIR="${SCRIPT_DIR}"
TARGET_DIR="${HOME}/PeerTube-client-dev"

if [[ ! -d "${SOURCE_CLIENT_DIR}" ]]; then
  echo "Client directory not found: ${SOURCE_CLIENT_DIR}" >&2
  exit 1
fi

mkdir -p "${TARGET_DIR}"

if [[ "${SOURCE_CLIENT_DIR}" == "${TARGET_DIR}" ]]; then
  echo "Source and target are the same, rsync skipped."
else
  echo "Rsync client -> ${TARGET_DIR}"
  rsync -a --delete \
    --exclude "node_modules/" \
    --exclude "dist/" \
    "${SOURCE_CLIENT_DIR}/" "${TARGET_DIR}/"
fi

cd "${TARGET_DIR}"

echo "npm install"
npm install

echo "npm run build"
npm run build

echo "Done."
