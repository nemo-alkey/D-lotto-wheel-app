#!/bin/bash
set -euo pipefail

DEVICE="/dev/sda1"
MOUNT="/media/racing_dev/FBC2-0CF4"
SOURCE="$HOME/lotto-wheel-app"
TARGET="$MOUNT/lotto-wheel-app"

# 1. Mount USB if not already mounted
if ! mountpoint -q "$MOUNT"; then
    echo "[1/4] Mounting $DEVICE at $MOUNT..."
    sudo mount -o "uid=$(id -u),gid=$(id -g)" "$DEVICE" "$MOUNT"
else
    echo "[1/4] $DEVICE already mounted at $MOUNT"
fi

# 2. Sync app dir if missing
if [ ! -d "$TARGET" ]; then
    echo "[2/4] Copying app to $TARGET (excluding venv)..."
    rsync -a --exclude=venv "$SOURCE"/ "$TARGET"/
else
    echo "[2/4] $TARGET already exists"
fi

# 3. Ensure streamlit + pandas are available
echo "[3/4] Checking Python packages..."
python3 -c "import streamlit, pandas" 2>/dev/null \
    || pip3 install --user streamlit pandas 2>&1 | tail -2

# 4. Launch dashboard
echo "[4/4] Starting Streamlit dashboard..."
cd "$TARGET"
exec python3 -m streamlit run dashboard.py
