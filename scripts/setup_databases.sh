#!/bin/bash
# Point dataset/databases at a local directory of SQLite databases.
# If the path already exists (including a symlink), leave it alone.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/dataset/databases"
SRC="${1:-${ASK_DATABASES:-}}"

if [[ -e "${DEST}" || -L "${DEST}" ]]; then
    if [[ -L "${DEST}" ]]; then
        echo "dataset/databases already exists -> $(readlink "${DEST}")"
    else
        echo "dataset/databases already exists: ${DEST}"
    fi
    exit 0
fi

if [[ -z "${SRC}" ]]; then
    echo "usage: ASK_DATABASES=/path/to/sqlite/roots bash scripts/setup_databases.sh" >&2
    echo "   or: bash scripts/setup_databases.sh /path/to/sqlite/roots" >&2
    echo "See dataset/DATABASES.md for the expected layout." >&2
    exit 1
fi
if [[ ! -d "${SRC}" ]]; then
    echo "not a directory: ${SRC}" >&2
    exit 1
fi
ln -s "$(cd "${SRC}" && pwd)" "${DEST}"
echo "linked dataset/databases -> $(readlink "${DEST}")"
