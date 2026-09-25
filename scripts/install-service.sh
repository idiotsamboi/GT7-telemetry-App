#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(id -u)" -eq 0 ]; then echo 'Use a normal user: audio needs your desktop session.'; exit 1; fi
project_path="$(pwd)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/gt7-engineer.service" <<EOF
[Unit]
Description=GT7 Race Engineer
After=network.target pipewire.service
[Service]
Type=simple
WorkingDirectory="$project_path"
ExecStart="$project_path/.venv/bin/python" "$project_path/run.py"
Environment=OMP_NUM_THREADS=2
Environment=OPENBLAS_NUM_THREADS=1
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now gt7-engineer
printf 'User service enabled. Logs: journalctl --user -u gt7-engineer -f\n'
