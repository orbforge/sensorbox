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
    IMAGE_PATTERN="$1"
else
    # List available squashfs images across all build dirs
    echo "Available images:"
    echo
    find "$STORE_DIR" -name '*squashfs-sysupgrade.img.gz' -newer "$STORE_DIR" -o -name '*squashfs-sysupgrade.img.gz' | sort -t/ -k6 | while read -r f; do
        echo "  $(basename "$f")"
    done | sort -u
    echo
    read -rp "Image filename (or substring): " IMAGE_PATTERN
fi

# Search for matching image in the store
IMAGE_PATH=$(find "$STORE_DIR" -name "*${IMAGE_PATTERN}*" -type f 2>/dev/null | head -1)
[[ -n "$IMAGE_PATH" ]] || die "No image matching '$IMAGE_PATTERN' found in $STORE_DIR"

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
