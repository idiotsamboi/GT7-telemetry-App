#!/bin/sh
set -eu
ROOT=/opt/gt7-race-engineer
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/gt7-race-engineer"
mkdir -p "$DATA"
exec 9>"$DATA/setup.lock"
flock 9
VERSION="$(cat "$ROOT/RELEASE")-$(python3 -c 'import sys;print(sys.version_info.minor)')"
ENV="$DATA/runtime-$VERSION"
if [ ! -f "$ENV/.ready" ]; then
    python3 -m venv --system-site-packages "$ENV"
    "$ENV/bin/python" -m pip install --no-index --find-links "$ROOT/wheels" -r "$ROOT/requirements-desktop.txt" >"$DATA/install.log" 2>&1 || {
        zenity --error --text="GT7 setup failed. See $DATA/install.log"; exit 1;
    }
    touch "$ENV/.ready"
fi
flock -u 9
exec "$ENV/bin/python" "$ROOT/desktop.py"
