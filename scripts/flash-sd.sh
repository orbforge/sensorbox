#!/bin/bash
# Flash an orb-forge image to an SD card for local development testing.
#
# Usage:
#   ./scripts/flash-sd.sh <image-filename>
#   ./scripts/flash-sd.sh    (lists available images and prompts)
#
# The image is expected to be in public/store/*/. The script finds it
# by filename across all build hash directories.

set -euo pipefail

STORE_DIR="$(cd "$(dirname "$0")/.." && pwd)/public/store"
SD_DISK="/dev/disk8"
SD_RDISK="/dev/rdisk8"
LOCAL_DIR="/tmp/orb-forge-flash"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ "$(uname)" == "Darwin" ]] || die "This script is for macOS only"

# Find the image
if [[ $# -ge 1 ]]; then
    # Direct substring match, newest first
    IMAGE_PATH=$(find "$STORE_DIR" -name "*${1}*" -type f 2>/dev/null | xargs ls -t 2>/dev/null | head -1)
    [[ -n "$IMAGE_PATH" ]] || die "No image matching '$1' found in $STORE_DIR"
else
    # Build a list of squashfs images, newest first, with timestamps
    IMAGE_LIST=$(find "$STORE_DIR" -name '*squashfs-sysupgrade.img.gz' -type f | xargs ls -t 2>/dev/null | while read -r f; do
        ts=$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$f")
        echo "[$ts]  $(basename "$f")|$f"
    done)
    [[ -n "$IMAGE_LIST" ]] || die "No images found in $STORE_DIR"

    if command -v fzf >/dev/null 2>&1; then
        SELECTION=$(echo "$IMAGE_LIST" | cut -d'|' -f1 | fzf --height=15 --reverse --prompt="Select image: ") || die "No image selected"
        IMAGE_PATH=$(echo "$IMAGE_LIST" | grep -F "$SELECTION" | head -1 | cut -d'|' -f2)
    else
        echo "Available images (newest first):"
        echo
        echo "$IMAGE_LIST" | cut -d'|' -f1 | cat -n
        echo
        read -rp "Enter number: " NUM
        IMAGE_PATH=$(echo "$IMAGE_LIST" | sed -n "${NUM}p" | cut -d'|' -f2)
    fi
    [[ -n "$IMAGE_PATH" ]] || die "Invalid selection"
fi

IMAGE_NAME=$(basename "$IMAGE_PATH")
echo "Image: $IMAGE_NAME"
echo "  From: $IMAGE_PATH"

# Verify SD card is present
diskutil info "$SD_DISK" >/dev/null 2>&1 || die "SD card not found at $SD_DISK — check 'diskutil list' and update SD_DISK in this script"

echo "Target: $SD_DISK ($(diskutil info -plist "$SD_DISK" | plutil -extract Size raw -) bytes)"
echo
echo "This will ERASE $SD_DISK. Press Enter to continue or Ctrl-C to abort."
read -r

mkdir -p "$LOCAL_DIR"

# Decompress — OpenWrt images have trailing metadata that gzip warns about
echo "==> Decompressing..."
gzip -dc "$IMAGE_PATH" > "$LOCAL_DIR/${IMAGE_NAME%.gz}" 2>/dev/null || true
LOCAL_IMG="$LOCAL_DIR/${IMAGE_NAME%.gz}"
[[ -s "$LOCAL_IMG" ]] || die "Decompression produced empty file"

IMG_SIZE=$(stat -f%z "$LOCAL_IMG")
IMG_BLOCKS=$(( (IMG_SIZE + 1048575) / 1048576 ))
echo "    Image: $IMG_SIZE bytes ($IMG_BLOCKS MiB)"

echo "==> Computing source checksum..."
SRC_SHA=$(shasum -a 256 "$LOCAL_IMG" | awk '{print $1}')
echo "    Source: $SRC_SHA"

echo "==> Unmounting $SD_DISK..."
diskutil unmountDisk "$SD_DISK" || die "Failed to unmount $SD_DISK"

echo "==> Writing to $SD_RDISK..."
sudo dd if="$LOCAL_IMG" of="$SD_RDISK" bs=1m status=progress
sync

echo "==> Unmounting before verify..."
diskutil unmountDisk "$SD_DISK" 2>/dev/null || true
sleep 1

echo "==> Verifying write..."
DISK_SHA=$(sudo dd if="$SD_RDISK" bs=1m count="$IMG_BLOCKS" 2>/dev/null | head -c "$IMG_SIZE" | shasum -a 256 | awk '{print $1}')
echo "    Disk:   $DISK_SHA"

if [[ "$SRC_SHA" == "$DISK_SHA" ]]; then
    echo "==> Checksum OK — image verified"
else
    die "Checksum MISMATCH — flash may be corrupted, try again"
fi

diskutil eject "$SD_DISK"
echo "==> Done! SD card ejected safely."
