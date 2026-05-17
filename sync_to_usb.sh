#!/bin/bash
set -euo pipefail

DEVICE="/dev/sda1"
MOUNT_POINT="/media/racing_dev/FBC2-0CF4"
SOURCE_DIR="$HOME/lotto-wheel-app"
TARGET_DIR="$MOUNT_POINT/lotto-wheel-app"

# 1. Ensure mount point exists
if [ ! -d "$MOUNT_POINT" ]; then
    mkdir -p "$MOUNT_POINT"
fi

# 2. Mount device if not already mounted
if ! mountpoint -q "$MOUNT_POINT"; then
    UID_CURRENT=$(id -u)
    GID_CURRENT=$(id -g)
    mount -o "uid=$UID_CURRENT,gid=$GID_CURRENT" "$DEVICE" "$MOUNT_POINT"
    echo "Mounted $DEVICE at $MOUNT_POINT (uid=$UID_CURRENT, gid=$GID_CURRENT)"
else
    echo "$DEVICE is already mounted at $MOUNT_POINT"
fi

# 3. Copy project directory, excluding venv
echo "Copying $SOURCE_DIR to $TARGET_DIR (excluding venv)..."

cd /
rsync -a --delete --exclude='venv' "$SOURCE_DIR"/ "$TARGET_DIR"/

if [ -d "$TARGET_DIR/venv" ]; then
    rm -rf "$TARGET_DIR/venv"
fi
echo "Sync complete."
