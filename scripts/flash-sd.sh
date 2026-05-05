#!/bin/bash
# Flash an orb-forge image to an SD card for local development testing.
#
# Usage:
#   ./scripts/flash-sd.sh <image-substring>
#   ./scripts/flash-sd.sh    (interactive selection of image + disk)
#
# The image is expected to be in public/store/*/. The script finds it
# by filename across all build hash directories.
#
# Requires: fzf (brew install fzf) for interactive selection, or
# falls back to numbered menus.

set -euo pipefail

STORE_DIR="$(cd "$(dirname "$0")/.." && pwd)/public/store"
LOCAL_DIR="/tmp/orb-forge-flash"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ "$(uname)" == "Darwin" ]] || die "This script is for macOS only"

# --- Image selection ---

if [[ $# -ge 1 ]]; then
    IMAGE_PATH=$(find "$STORE_DIR" -name "*${1}*" -type f 2>/dev/null | xargs ls -t 2>/dev/null | head -1)
    [[ -n "$IMAGE_PATH" ]] || die "No image matching '$1' found in $STORE_DIR"
else
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

# --- Disk selection ---

# Build a list of external/removable disks (skip internal disks).
# Shows device name, size, and media name for easy identification.
select_disk() {
    local DISK_LIST=""
    for disk in /dev/disk[0-9]*; do
        # Skip partition entries (disk0s1, etc.)
        [[ "$disk" =~ s[0-9]+$ ]] && continue
        # Only consider whole disks
        local info
        info=$(diskutil info -plist "$disk" 2>/dev/null) || continue
        local removable ejectable size_bytes size_gb name protocol
        removable=$(echo "$info" | plutil -extract Removable raw - 2>/dev/null || echo "false")
        ejectable=$(echo "$info" | plutil -extract Ejectable raw - 2>/dev/null || echo "false")
        [[ "$removable" == "true" || "$ejectable" == "true" ]] || continue
        protocol=$(echo "$info" | plutil -extract BusProtocol raw - 2>/dev/null || echo "")
        # Skip disk images (mounted .dmg, Podman container volumes, etc.)
        [[ "$protocol" == "Disk Image" ]] && continue
        size_bytes=$(echo "$info" | plutil -extract Size raw - 2>/dev/null || echo 0)
        size_gb=$(( size_bytes / 1073741824 ))
        name=$(echo "$info" | plutil -extract MediaName raw - 2>/dev/null || echo "Unknown")
        DISK_LIST+="${disk}  ${size_gb}GB  ${name}  (${protocol})|${disk}"$'\n'
    done

    [[ -n "$DISK_LIST" ]] || die "No removable/external disks found. Insert an SD card and try again."

    local selected_disk
    if command -v fzf >/dev/null 2>&1; then
        local selection
        selection=$(echo "$DISK_LIST" | cut -d'|' -f1 | fzf --height=10 --reverse --prompt="Select target disk: ") || die "No disk selected"
        selected_disk=$(echo "$DISK_LIST" | grep -F "$selection" | head -1 | cut -d'|' -f2)
    else
        echo "Removable disks:"
        echo
        echo "$DISK_LIST" | cut -d'|' -f1 | cat -n
        echo
        read -rp "Enter number: " NUM
        selected_disk=$(echo "$DISK_LIST" | sed -n "${NUM}p" | cut -d'|' -f2)
    fi

    [[ -n "$selected_disk" ]] || die "Invalid selection"
    echo "$selected_disk"
}

SD_DISK=$(select_disk)
SD_RDISK="${SD_DISK/disk/rdisk}"

echo "Target: $SD_DISK"
diskutil info "$SD_DISK" | grep -E 'Device / Media Name|Disk Size|Protocol' | sed 's/^/  /'
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
