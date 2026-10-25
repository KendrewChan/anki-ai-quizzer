#!/usr/bin/env bash
# Copy addon/ into an Anki add-ons folder that is not a symlink to this repo
# (e.g. Windows Anki driven from WSL). Keeps the live meta.json and user_files/.
# Usage: ANKI_ADDONS_DIR=/mnt/c/Users/<name>/AppData/Roaming/Anki2/addons21 scripts/deploy.sh
set -euo pipefail
: "${ANKI_ADDONS_DIR:?set ANKI_ADDONS_DIR to the Anki addons21 folder}"
cd "$(dirname "$0")/.."
dest="$ANKI_ADDONS_DIR/anki_ai"
mkdir -p "$dest"
rsync -rlt --delete --exclude meta.json --exclude user_files --exclude __pycache__ addon/ "$dest/"
diff -rq addon "$dest" -x __pycache__ -x meta.json -x user_files && echo "Synced. Restart Anki to load it."
