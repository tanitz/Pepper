#!/usr/bin/env bash
# Download SoftBank pynaoqi 2.8.7.4 (linux64) into SDK_pynaoqi/linux64/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${ROOT}/SDK_pynaoqi/linux64"
QI_SO="${DEST}/lib/python2.7/site-packages/_qi.so"

URL="https://media.githubusercontent.com/media/snc-iiot/nao6-doc-sdk/master/pynaoqi-python2.7-2.8.7.4-linux64-20210819_141148.tar.gz"
EXPECTED_SHA256="ad60c9336376bd56d3ab2fbcbb9f249f65747bf65869624a2ce4b9112cc50cd9"

if [[ -f "${QI_SO}" ]]; then
  echo "Linux NAOqi SDK already present: ${QI_SO}"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

ARCHIVE="${TMP}/pynaoqi-linux64.tar.gz"
echo "==> Downloading pynaoqi linux64 (~199 MB)..."
curl -L --fail --progress-bar -o "${ARCHIVE}" "${URL}"

echo "==> Verifying SHA256..."
ACTUAL="$(shasum -a 256 "${ARCHIVE}" | awk '{print $1}')"
if [[ "${ACTUAL}" != "${EXPECTED_SHA256}" ]]; then
  echo "ERROR: checksum mismatch" >&2
  echo "  expected: ${EXPECTED_SHA256}" >&2
  echo "  actual:   ${ACTUAL}" >&2
  exit 1
fi

echo "==> Extracting to SDK_pynaoqi/linux64/..."
mkdir -p "${ROOT}/SDK_pynaoqi"
tar -xzf "${ARCHIVE}" -C "${TMP}"
EXTRACTED="$(find "${TMP}" -maxdepth 1 -type d -name 'pynaoqi-python2.7-*-linux64*' | head -1)"
rm -rf "${DEST}"
mv "${EXTRACTED}" "${DEST}"

if [[ ! -f "${QI_SO}" ]]; then
  echo "ERROR: _qi.so not found after extract at ${QI_SO}" >&2
  exit 1
fi

echo "Done. SDK ready at ${DEST}"
echo "Verify with: python2 naoqi_path.py"
