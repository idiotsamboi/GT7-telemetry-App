#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(id -u)" -eq 0 ]; then echo 'Run as your normal desktop user, not root.'; exit 1; fi
printf 'Machine: '; uname -m
cat /etc/os-release
if [ -f /proc/device-tree/model ]; then tr -d '\0' </proc/device-tree/model; printf '\n'; fi
printf '\nInstalling Ubuntu native prerequisites (sudo is used only for apt).\n'
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-dev libportaudio2 portaudio19-dev espeak-ng alsa-utils build-essential
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required; do not replace system Python"'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
if [ ! -f frontend/dist/index.html ]; then
  echo 'Compiled UI missing. Install Node 20.19+ for building, then run: cd frontend && npm ci && npm run build'
  exit 1
fi
.venv/bin/python run.py diagnostics
printf '\nInstalled. Start: ./scripts/launch.sh --demo\nOffline microphone optional: .venv/bin/pip install -r requirements-voice.txt\n'
