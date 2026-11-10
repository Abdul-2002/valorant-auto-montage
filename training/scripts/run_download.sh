#!/bin/bash
set -euo pipefail
cd /mnt/c/Users/aasid/OneDrive/Documents/valorant-montage-bot
python3 -m pip install --user "roboflow>=1.1.0" -q
export PATH="$HOME/.local/bin:$PATH"
python3 training/scripts/check_roboflow_key.py
python3 training/scripts/download_roboflow_raw.py
